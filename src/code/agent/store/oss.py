import os
import time
from urllib.parse import urlparse, urlunparse
import oss2
import constants
from utils.logger import log


class OSS:

    def __init__(
        self,
        endpoint,
        access_key_id,
        access_key_secret,
        security_token="",
        output_folder="comfyui_serverless_api",
        expires_in_second: int = 0,
    ):
        self.oss_bucket = None
        self.region = None
        self.bucket_name = None
        self.oss_endpoint = endpoint
        self.oss_bucket_key_prefix = output_folder.strip("/ ")
        self.oss_expires = 0
        
        # 只有传入了 expires_in_second 才做类型转换
        if expires_in_second:
            try:
                self.oss_expires = int(expires_in_second)
            except Exception as e:
                log("WARNING", f"OSS expires '{expires_in_second}' is invalid number: {e}")

        arr = self.oss_endpoint.split(".")
        if not (
            len(arr) == 4
            and arr[1].startswith("oss-")
            and arr[2] == "aliyuncs"
            and arr[3] == "com"
        ):
            log("DEBUG", f"OSS endpoint '{self.oss_endpoint}' is invalid (expected format: bucket.oss-region.aliyuncs.com)")
            return

        self.bucket_name = arr[0].split("/")[-1] if "/" in arr[0] else arr[0]
        self.region = arr[1].removeprefix("oss-").removesuffix("-internal")
        protocol = "https://" if self.oss_endpoint.startswith("https://") else "http://"

        auth_type = "STS" if security_token else "AccessKey"
        self.oss_bucket = oss2.Bucket(
            (
                oss2.StsAuth(access_key_id, access_key_secret, security_token)
                if security_token
                else oss2.Auth(access_key_id, access_key_secret)
            ),
            protocol + ".".join(arr[1:]),
            self.bucket_name,
        )
        
        log("INFO", f"OSS client initialized: bucket={self.bucket_name}, region={self.region}, "
             f"prefix={self.oss_bucket_key_prefix}, auth={auth_type}, expires={self.oss_expires}s")

    def __file_path(self, key: str):
        return os.path.join(self.oss_bucket_key_prefix, key)

    def ready(self):
        return self.oss_bucket is not None

    def get(self, key: str) -> str:
        if not self.ready():
            log("ERROR", "OSS client is not initialized, cannot get object")
            return ""

        try:
            object_key = self.__file_path(key)
            log("DEBUG", f"getting OSS object: {object_key}")
            
            start_time = time.perf_counter()
            with self.oss_bucket.get_object(object_key) as f:
                content = f.read()
            elapsed = time.perf_counter() - start_time
            
            log("INFO", f"successfully retrieved OSS object: {object_key} ({len(content)} bytes) in {elapsed:.2f}s")
            return content
        except Exception as e:
            # 忽略"文件不存在"的错误（正常情况）
            if "NoSuchKey" in str(e) or "No such file" in str(e):
                log("DEBUG", f"OSS object not found: {key}")
            else:
                log("ERROR", f"failed to get OSS object '{key}': {e}")
            return ""

    def put(self, key: str, value: str):
        if not self.ready():
            log("ERROR", "OSS client is not initialized, cannot put object")
            return

        try:
            object_key = self.__file_path(key)
            data_size = len(value) if isinstance(value, (str, bytes)) else "unknown"
            log("DEBUG", f"putting OSS object: {object_key} ({data_size} bytes)")
            
            start_time = time.perf_counter()
            self.oss_bucket.put_object(object_key, value)
            elapsed = time.perf_counter() - start_time
            
            log("INFO", f"successfully uploaded to OSS: {object_key} ({data_size} bytes) in {elapsed:.2f}s")
        except Exception as e:
            log("ERROR", f"failed to put OSS object '{key}': {e}")
            import traceback
            traceback.print_exc()

    def sign(self, key: str, expires_in_second=None):
        """
        针对特定的数据进行签名，允许匿名访问
        """
        if not self.ready():
            log("ERROR", "OSS client is not initialized, cannot sign URL")
            raise Exception("oss client is not init")

        if expires_in_second is None:
            expires_in_second = self.oss_expires

        # 如果 expires_in_second 未配置或 <= 0，打印 debug 日志并返回空字符串
        if expires_in_second <= 0:
            log("DEBUG", f"OSS expires is not configured (current: {expires_in_second}), skipping URL signing for key: {key}")
            return ""

        # 正常签名流程
        log("DEBUG", f"signing OSS URL for key: {key}, expires in {expires_in_second}s")
        
        start_time = time.perf_counter()
        u = self.oss_bucket.sign_url(
            "GET", self.__file_path(key), expires_in_second, slash_safe=True
        )

        # url can visit on interet
        parsed = urlparse(u)
        host_parts = parsed.hostname.split(".")

        if (constants.OSS_OUTPUT_DOMAIN):
            parsed = parsed._replace(netloc=constants.OSS_OUTPUT_DOMAIN)
            u = urlunparse(parsed)
        elif (
            len(host_parts) == 4
            and host_parts[2] == "aliyuncs"
            and host_parts[3] == "com"
            and host_parts[1].startswith("oss-")
            and host_parts[1].endswith("-internal")
        ):
            # 去掉 "-internal"
            host_parts[1] = host_parts[1].removesuffix("-internal")
            new_hostname = ".".join(host_parts)
            if parsed.port:  # 保留端口（如果有）
                new_hostname += f":{parsed.port}"

            # 替换 netloc，重建 URL
            parsed = parsed._replace(netloc=new_hostname)
            u = urlunparse(parsed)

        elapsed = time.perf_counter() - start_time
        log("INFO", f"successfully signed OSS URL: {u[:100]}... in {elapsed:.2f}s")
        return u

    def object_key(self, key: str):
        """
        返回 OSS 中存储的实际 object key
        """
        return self.__file_path(key)
