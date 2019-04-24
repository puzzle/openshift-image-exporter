#!/usr/bin/env python3

import logging
import os
import time

import kubernetes
import openshift.dynamic
import openshift.dynamic.exceptions
import prometheus_client
import urllib3
import dateutil.parser

from prometheus_client.core import GaugeMetricFamily, REGISTRY

IMAGE_METRIC_FAMILY = GaugeMetricFamily('container_image_creation_timestamp', 'Creation timestamp of container image', labels=['namespace', 'pod_container', 'image'])
BASE_IMAGE_METRIC_FAMILY = GaugeMetricFamily('container_base_image_creation_timestamp', 'Creation timestamp of container base image', labels=['namespace', 'pod_container', 'image'])

class CustomCollector(object):
    def __init__(self):
        if 'KUBERNETES_PORT' in os.environ:
            kubernetes.config.load_incluster_config()
        else:
            kubernetes.config.load_kube_config()
        k8s_client = kubernetes.client.api_client.ApiClient(kubernetes.client.Configuration())
        self.dyn_client = openshift.dynamic.DynamicClient(k8s_client)

        self.image_metric_family = None
        self.base_image_metric_family = None

    def collect(self):
        if self.image_metric_family:
            yield self.image_metric_family
        if self.base_image_metric_family:
            yield self.base_image_metric_family

    @staticmethod
    def to_timestamp(date):
        return dateutil.parser.parse(date).timestamp()

    @staticmethod
    def find_base_image(images, digest):
        """Returns the base image of *digest*.

        Finds the image that shares the most first n layers with the given image.
        """

        image = images[digest]
        if image:
            layers = image['layers']
            while len(layers) > 0:
                layers = layers[:-1]
                base_image = images.get(layers)
                if base_image:
                    return base_image

        return None

    def update(self):
        logging.info(f"Collecting container image metrics")

        v1_image = self.dyn_client.resources.get(api_version='v1', kind='Image')
        images = {}
        for image in v1_image.get().items:
            digest = image['metadata']['name']
            if image['dockerImageLayers']:
                layers = tuple(layer['name'] for layer in image['dockerImageLayers'])
            else:
                layers = tuple()

            images[digest] = {'name': image['dockerImageReference'], 'created': image['dockerImageMetadata']['Created'], 'layers': layers}
            if layers:
                images[layers] = images[digest]

        image_metric_family = GaugeMetricFamily('container_image_creation_timestamp', 'Creation timestamp of container image', labels=['namespace', 'pod_container', 'image'])
        base_image_metric_family = GaugeMetricFamily('container_base_image_creation_timestamp', 'Creation timestamp of container base image', labels=['namespace', 'pod_container', 'image'])

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
                image_metadata = images.get(digest)

                if image_metadata:
                    image_creation_timestamp = self.to_timestamp(image_metadata['created'])
                    base_image = self.find_base_image(images, digest)
                else:
                    base_image = None
                    image_creation_timestamp = 0

                if base_image:
                    base_image_name = base_image['name']
                    base_image_creation_timestamp = self.to_timestamp(base_image['created'])
                else:
                    base_image_name = '<unknown>'
                    base_image_creation_timestamp = 0

                image_metric_family.add_metric([namespace, pod_container, image_name], image_creation_timestamp)
                base_image_metric_family.add_metric([namespace, pod_container, base_image_name], base_image_creation_timestamp)

                container_count += 1

        self.image_metric_family = image_metric_family
        self.base_image_metric_family = base_image_metric_family

        logging.info(f"Collected image metrics for {container_count} running containers")

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
