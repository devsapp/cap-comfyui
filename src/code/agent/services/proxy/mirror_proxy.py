import os

from mitmproxy import http


def request(flow: http.HTTPFlow) -> None:
    region = os.getenv("REGION")
    target_hosts = ["github.com", "huggingface.co", "raw.githubusercontent.com"]
    mirror_host = f"{region}.mirrors.functionai.aliyuncs.com"

    if flow.request.pretty_host in target_hosts:
        origin = f"{flow.request.scheme}://{flow.request.host}{flow.request.path}"

        # build request to cap mirror
        mirror_path = f"/proxy/{flow.request.host}{flow.request.path}"
        # print(f"Proxy to cap mirror with mirror_path '{mirror_path}' and origin url '{origin}'", )

        # proxy request
        flow.request.host = mirror_host
        flow.request.port = 80
        flow.request.scheme = "http"
        flow.request.path = mirror_path
