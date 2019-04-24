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

IMAGE_CREATION_TIMESTAMP = prometheus_client.Gauge('container_image_creation_timestamp', 'Creation timestamp of container image', labelnames=['namespace', 'pod_container', 'image'])
BASE_IMAGE_CREATION_TIMESTAMP = prometheus_client.Gauge('container_base_image_creation_timestamp', 'Creation timestamp of container base image', labelnames=['namespace', 'pod_container', 'image'])

def to_timestamp(date):
    return dateutil.parser.parse(date).timestamp()

def find_base_image(images, digest):
    image = images[digest]
    if image:
        layers = image['layers']
        while len(layers) > 0:
            layers = layers[:-1]
            base_image = images.get(layers)
            if base_image:
                return base_image

    return None

def collect_image_metrics(dyn_client):
    logging.info(f"Collecting container image metrics")
    v1_image = dyn_client.resources.get(api_version='v1', kind='Image')
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

    v1_pod = dyn_client.resources.get(api_version='v1', kind='Pod')
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
                image_creation_timestamp = to_timestamp(image_metadata['created'])
                base_image = find_base_image(images, digest)
            else:
                base_image = None
                image_creation_timestamp = 0

            if base_image:
                base_image_name = base_image['name']
                base_image_creation_timestamp = to_timestamp(base_image['created'])
            else:
                base_image_name = '<unknown>'
                base_image_creation_timestamp = 0

            IMAGE_CREATION_TIMESTAMP.labels(namespace, pod_container, image_name).set(image_creation_timestamp)
            BASE_IMAGE_CREATION_TIMESTAMP.labels(namespace, pod_container, base_image_name).set(base_image_creation_timestamp)

            container_count += 1

    logging.info(f"Collected image metrics for {container_count} running containers")

if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

    # Disable SSL warnings: https://urllib3.readthedocs.io/en/latest/advanced-usage.html#ssl-warnings
    urllib3.disable_warnings()

    if 'KUBERNETES_PORT' in os.environ:
        kubernetes.config.load_incluster_config()
    else:
        kubernetes.config.load_kube_config()
    k8s_client = kubernetes.client.api_client.ApiClient(kubernetes.client.Configuration())
    dyn_client = openshift.dynamic.DynamicClient(k8s_client)

    interval = int(os.getenv('IMAGE_METRICS_INTERVAL', '300'))
    prometheus_client.start_http_server(8080)
    while True:
        try:
            collect_image_metrics(dyn_client)
        except Exception as e:
            logging.exception(e)
        time.sleep(interval)
