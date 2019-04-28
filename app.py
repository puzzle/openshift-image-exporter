#!/usr/bin/env python3

import logging
import os
import time

import pathlib
import kubernetes
import openshift.dynamic
import openshift.dynamic.exceptions
import prometheus_client
import urllib3
import dateutil.parser

from prometheus_client.core import GaugeMetricFamily, REGISTRY
from openshift.dynamic.exceptions import NotFoundError

IMAGE_METRIC_FAMILY = GaugeMetricFamily('container_image_creation_timestamp', 'Creation timestamp of container image', labels=['namespace', 'pod_container', 'image'])
BASE_IMAGE_METRIC_FAMILY = GaugeMetricFamily('container_base_image_creation_timestamp', 'Creation timestamp of container base image', labels=['namespace', 'pod_container', 'image'])

class CustomCollector(object):
    def __init__(self):
        if 'KUBERNETES_PORT' in os.environ:
            kubernetes.config.load_incluster_config()
            self.namespace = pathlib.Path('/var/run/secrets/kubernetes.io/serviceaccount/namespace').read_text()
        else:
            kubernetes.config.load_kube_config()
            _, active_context = kubernetes.config.list_kube_config_contexts()
            self.namespace = active_context['context']['namespace']
        k8s_client = kubernetes.client.api_client.ApiClient(kubernetes.client.Configuration())
        self.dyn_client = openshift.dynamic.DynamicClient(k8s_client)

        self.image_metric_family = None
        self.base_image_metric_family = None

    def collect(self):
        if self.image_metric_family:
            yield self.image_metric_family
        if self.base_image_metric_family:
            yield self.base_image_metric_family

    def update(self):
        collectorUpdater = CustomCollectorUpdater(self.dyn_client, self.namespace)
        self.image_metric_family, self.base_image_metric_family = collectorUpdater.run()


class CustomCollectorUpdater(object):
    def __init__(self, dyn_client, namespace):
        self.dyn_client = dyn_client
        self.namespace = namespace
        # self.images = {}
        # self.built_images = {}
        # self.missing_images = set()

    def find_base_image(self, digest):
        """Returns the base image of *digest*.

        Finds the image that shares the most first n layers with the given image.
        """

        base_image = self.built_images.get(digest)
        if base_image:
            base_digest = base_image.split('@')[1]
            if base_digest in self.images:
                return self.images[base_digest]
            else:
                self.missing_images.add(base_image)

        image = self.images[digest]
        if image:
            layers = image['layers']
            while len(layers) > 0:
                layers = layers[:-1]
                base_image = self.images.get(layers)
                if base_image:
                    return base_image

        return None

    def update_missing_imagestream(self):
        v1_imagestream = self.dyn_client.resources.get(api_version='v1', kind='ImageStream')
        try:
            image_stream = v1_imagestream.get(namespace=self.namespace, name='openshift-image-exporter-info')
            #old_image_stream = v1_imagestream.get(namespace=self.namespace, name='openshift-image-exporter-info')
        except NotFoundError:
            image_stream = {
                'apiVersion': "v1",
                'kind': "ImageStream",
                'metadata': {
                    'name': 'openshift-image-exporter-info',
                    #'namespace': memcached['metadata']['namespace'],
                },
                'spec': {
                    'tags': []
                }
            }

        for image in self.missing_images:
            image_stream['spec']['tags'].append({
                'name': image.split('@')[1].replace(':', '-'),
                'from': {
                    'kind': 'DockerImage',
                    'name': image
                },
                'referencePolicy': {
                    'type': 'Source'
                }
            })

        #tags = image_stream['spec']['tags']
        #tags[:] = [tag for tag in tags if tag['name'].replace('-', ':') in images]
        # for tag in tags:
        #     digest = tag['name'].replace('-', ':')
        #     if digest not in images:
        #         print(digest)

        #print(jsonpatch.JsonPatch.from_diff(old_image_stream['spec'], image_stream['spec']))
        if image_stream.get('status'):
            v1_imagestream.replace(namespace=self.namespace, body=image_stream)
        else:
            v1_imagestream.create(body=image_stream, namespace=self.namespace)

    def fetch_built_images(self):
        v1_build = self.dyn_client.resources.get(api_version='v1', kind='Build')
        self.built_images = {}
        for build in v1_build.get().items:
            base_image = build['spec']['strategy'].get('dockerStrategy', {}).get('from', {}).get('name') or build['spec']['strategy'].get('sourceStrategy', {}).get('from', {}).get('name')
            output_image = build['status'].get('output', {}).get('to', {}).get('imageDigest', {})
            # if not base_image:
            #    base_image = build['spec']['strategy'].get('sourceStrategy', {}).get('from', {}).get('name')
            if base_image and output_image and '@' in base_image:
                self.built_images[output_image] = base_image

    def fetch_images(self):
        v1_image = self.dyn_client.resources.get(api_version='v1', kind='Image')
        self.images = {}
        for image in v1_image.get().items:
            digest = image['metadata']['name']
            if image['dockerImageLayers']:
                layers = tuple(layer['name'] for layer in image['dockerImageLayers'])
            else:
                layers = tuple()

            self.images[digest] = {'name': image['dockerImageReference'], 'created': image['dockerImageMetadata']['Created'], 'layers': layers}
            if layers:
                self.images[layers] = self.images[digest]


    def run(self):
        logging.info("Collecting container image metrics")

        self.fetch_images()
        self.fetch_built_images()

        image_metric_family = GaugeMetricFamily('container_image_creation_timestamp', 'Creation timestamp of container image', labels=['namespace', 'pod_container', 'image'])
        base_image_metric_family = GaugeMetricFamily('container_base_image_creation_timestamp', 'Creation timestamp of container base image', labels=['namespace', 'pod_container', 'image'])

        self.missing_images=set()
        v1_pod = self.dyn_client.resources.get(api_version='v1', kind='Pod')
        container_count = 0
        for pod in v1_pod.get().items:
            namespace = pod['metadata']['namespace']
            pod_name = pod['metadata']['name']
            container_statuses = pod['status']['containerStatuses']
            if pod['status']['phase'] != 'Running' or pod['deletionTimestamp']:
                continue
            for container_status in container_statuses:
                container_name = container_status['name']
                pod_container = pod_name + '/' + container_name
                image_id = container_status['imageID']
                if not image_id:
                    continue
                image_name = image_id.split('//')[1]
                digest = image_name.split('@')[1]
                image_metadata = self.images.get(digest)

                if image_metadata:
                    image_creation_timestamp = dateutil.parser.parse(image_metadata['created']).timestamp()
                    base_image = self.find_base_image(digest)
                else:
                    base_image = None
                    image_creation_timestamp = 0
                    self.missing_images.add(image_name)

                if base_image:
                    base_image_name = base_image['name']
                    base_image_creation_timestamp = dateutil.parser.parse(base_image['created']).timestamp()
                else:
                    base_image_name = '<unknown>'
                    base_image_creation_timestamp = 0

                image_metric_family.add_metric([namespace, pod_container, image_name], image_creation_timestamp)
                base_image_metric_family.add_metric([namespace, pod_container, base_image_name], base_image_creation_timestamp)

                container_count += 1

        self.update_missing_imagestream()

        logging.info(f"Collected image metrics for {container_count} running containers")

        return image_metric_family, base_image_metric_family


if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

    # Disable SSL warnings: https://urllib3.readthedocs.io/en/latest/advanced-usage.html#ssl-warnings
    urllib3.disable_warnings()

    interval = int(os.getenv('IMAGE_METRICS_INTERVAL', '300'))
    customCollector = CustomCollector()
    REGISTRY.register(customCollector)
    prometheus_client.start_http_server(8080)
    while True:
        try:
            customCollector.update()
        except Exception as e:
            logging.exception(e)
        time.sleep(interval)
