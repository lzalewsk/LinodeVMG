# -*- coding: utf-8 -*-
import os
import subprocess
import base64
import argparse
from linode_api4 import LinodeClient
from kubernetes import client, config, utils
from collections import Counter
from time import sleep
import configparser

# Load configuration from .ini file.
cfg = configparser.ConfigParser()
cfg.read('./config.ini')

LINODE_TOKEN  = cfg.get('LINODE', 'TOKEN')
TAGS          = cfg.get('LKE', 'TAGS').split(',')
LKE_LABEL     = cfg.get('LKE', 'LABEL')
TARGET_REGION = cfg.get('LKE', 'REGION')
KUBE_CONFIG_PATH = cfg.get('local', 'KUBE_CONFIG_PATH')

#
def check_if_lke_cluster_exists(ln_client, tags):
    """

    :param ln_client:
    :param tags:
    :return:
    """
    instances = ln_client.lke.clusters()
    lke_exist = False

    for instance in instances:
        if instance.tags <= tags:
            lke_exist = True
    return lke_exist


def create_lke(ln_client):
    """

    :param ln_client:
    :return:
    """

    # look up Region and Types to use.  In this example I'm just using
    # the first ones returned.
    # eu - central

    # available_regions = client.regions()
    # for region in available_regions:
    #     print(region)


    if not check_if_lke_cluster_exists(ln_client,TAGS):
        # create new cluster
        node_type = ln_client.linode.types()[1]
        # node_type_2 = client.linode.types()[1]
        kube_version = ln_client.lke.versions()[0]

        print(f'Starting new LKE with node_types: {node_type}')
        print(f'K8s version: {kube_version}')

        new_cluster = ln_client.lke.cluster_create(
            region=TARGET_REGION,
            label=LKE_LABEL,
            # node_pools  = [client.lke.node_pool(node_type, 3), client.lke.node_pool(node_type_2, 3)],
            node_pools=[ln_client.lke.node_pool(node_type, 3)],
            kube_version=kube_version,
            tags=TAGS
        )

    else:
        print(f'LKE with tags: {TAGS} exists')

    check_status(ln_client)
    get_lke_kubeconfig(ln_client)
    wait_for_all_pods_running()

def get_lke_kubeconfig(ln_client):
    """

    :param ln_client:
    :return:
    """
    instances = ln_client.lke.clusters()

    print('get LKE kubeconfoig')
    for instance in instances:
        if instance.tags <= TAGS:
            # write this config out to disk
            kubeconfig_ready = False
            while not kubeconfig_ready:
                try:
                    config = instance.kubeconfig
                    yaml_config = base64.b64decode(config)
                    with open("kubeconfig.yaml", "w") as f:
                        f.write(yaml_config.decode())
                        kubeconfig_ready = True
                except Exception as e:
                    print(e)
                sleep(10)
            os.environ["KUBECONFIG"] = os.path.join(os.getcwd(),'kubeconfig.yaml')

def del_lke_cluster(ln_client):
    instances = ln_client.lke.clusters()

    for instance in instances:
        print(instance)
        if instance.tags <= TAGS:
            instance.delete()

def check_status(ln_client):
    instances = ln_client.lke.clusters()

    for instance in instances:
        print(instance)
        print(instance.tags)

        if instance.tags <= TAGS:
            all_ready = False
            while not all_ready:
                status_list = []
                for pool in instance.pools:
                    for node in pool.nodes:
                        status_list.append(node.status)
                        # print(f"Node: {node.id} has status: {node.status}")

                # Check node status statistics
                status_counter = Counter(status_list)
                print(f"Status of nodes: {status_counter}")
                if (len(status_counter) == 1 and 'ready' in status_counter.keys()):
                    all_ready = True
                else:
                    sleep(5)
    print('K8s cluster stable')


def wait_for_all_pods_running(namespace = "kube-system"):
    """
    Metoda sprawdza status wszystkich podów w ramach danego namespac'u
    Czeka w pętli do momentu aż wszystkie pody uzyskają status Running
    :param namespace:
    :return:
    """
    config.load_kube_config(config_file=os.environ.get("KUBECONFIG",KUBE_CONFIG_PATH))
    k8s_api = client.CoreV1Api()
    print(f"Pods status check in namespace: {namespace}")
    all_ready = False
    while not all_ready:
        pod_status_list = []
        try:
            resp = k8s_api.list_namespaced_pod(namespace, watch=False)
            for i in resp.items:
                print(i.metadata.name + " " + i.status.phase)
                pod_status_list.append(i.status.phase)
        except Exception as e:
            print(f'Connnextion error: {e}')

        print('--------------------')
        # Check pods status statistics
        pod_status_counter = Counter(pod_status_list)
        print(f"Status of pods: {pod_status_counter}")
        if (len(pod_status_counter) == 1 and 'Running' in pod_status_counter.keys()):
            all_ready = True
        else:
            sleep(10)


def vmoperator_deploy():
    helm_cmd = "helm install vmoperator vm/victoria-metrics-operator -n victoriametrics --create-namespace -f vmetrics/vmoperator.yaml"
    subprocess.run(str.split(helm_cmd))
    wait_for_all_pods_running("victoriametrics")

def vmcluster_deploy():
    kubectl_cmd = "kubectl -n victoriametrics apply -f vmetrics/vmcluster.yaml"
    subprocess.run(str.split(kubectl_cmd))
    wait_for_all_pods_running("victoriametrics")


def vmcluster_delete():
    kubectl_cmd = "kubectl -n victoriametrics delete -f vmetrics/vmcluster.yaml"
    subprocess.run(str.split(kubectl_cmd))


def vmagent_deploy():
    kubectl_cmd = "kubectl -n victoriametrics delete -f vmetrics/vmagent.yaml"
    subprocess.run(str.split(kubectl_cmd))
    kubectl_cmd = "kubectl -n victoriametrics apply -f vmetrics/vmagent.yaml"
    subprocess.run(str.split(kubectl_cmd))
    wait_for_all_pods_running("victoriametrics")


def grafana_deploy():
    """
    Grafana deployment step by step with HELM
    :return:
    """
    helm_cmd = "helm repo add grafana https://grafana.github.io/helm-charts"
    subprocess.run(str.split(helm_cmd))
    helm_cmd = "helm repo update"
    subprocess.run(str.split(helm_cmd))
    helm_cmd = "helm install grafana grafana/grafana -n grafana --create-namespace -f grafana/grafana_helm_values.yaml"
    subprocess.run(str.split(helm_cmd))
    wait_for_all_pods_running("grafana")

    # check Grafana public IP
    kubectl_cmd = "kubectl get svc --namespace grafana grafana -o jsonpath='{.status.loadBalancer.ingress[0].ip}'"
    cp = subprocess.run(str.split(kubectl_cmd),capture_output=True)
    if cp.returncode > 0:
        printf(f'ERROR: {cp.stderr}')
    else:
        public_ip = cp.stdout.decode('ascii')[1:-1] # remove "'" from output

    # get Grafana Admin password
    kubectl_cmd = "kubectl get secret --namespace grafana grafana -o jsonpath='{.data.admin-password}'"
    cp = subprocess.run(str.split(kubectl_cmd),capture_output=True)
    if cp.returncode > 0:
        printf(f'ERROR: {cp.stderr}')
    else:
        admin_pass_b64 = cp.stdout
        admin_pass = base64.b64decode(admin_pass_b64).decode('ascii')

    print("################################################################################")
    print("#------------------------------------------------------------------------------#")
    print(f"#   Grafana shall be availablu on http://{public_ip}")
    print(f"#   Password for user admin is: {admin_pass}")
    print("#------------------------------------------------------------------------------#")
    print("################################################################################")

def clear_k8s_env():
    """
    K8s environment cleaning to remove resources like Volumes and NodeBalancers from Linode.
    :return:
    """
    helm_cmd = "helm delete -n grafana grafana"
    subprocess.run(str.split(helm_cmd))
    kubectl_cmd = "kubectl -n victoriametrics delete -f vmetrics/vmagent.yaml"
    subprocess.run(str.split(kubectl_cmd))
    kubectl_cmd = "kubectl -n victoriametrics delete -f vmetrics/vmcluster.yaml"
    subprocess.run(str.split(kubectl_cmd))
    helm_cmd = "helm -n victoriametrics delete vmoperator"
    subprocess.run(str.split(helm_cmd))
    kubectl_cmd = "kubectl delete namespace victoriametrics"
    subprocess.run(str.split(kubectl_cmd))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Simple LKE + VictoriaMetrics + Grafana setup')
    parser.add_argument("-c", "--create", help='create LKE Environment with VM + Grafana',
                        action="store_true")
    parser.add_argument("-d", "--delete", help='delete LKE Environment',
                        action="store_true")

    ln_client = LinodeClient(LINODE_TOKEN)
    args = parser.parse_args()
    if args.create:
        print('Starting LKE + VM + Grafana ....')
        create_lke(ln_client)
        vmoperator_deploy()
        vmcluster_deploy()
        vmagent_deploy()
        grafana_deploy()

    if args.delete:
        print('Buuu.....')
        clear_k8s_env()
        del_lke_cluster(ln_client)