import constants
from routes.routes import Routes
from services.comfyui_service import ComfyuiService
import threading


def run_agent_app(app):
    app.run(debug=False, host="0.0.0.0", port=9000)


def run_comfyui():
    service = ComfyuiService()
    service.start(constants.AUTO_LAUNCH_SNAPSHOT_NAME)


if __name__ == "__main__":
    r = Routes()

    if constants.AUTO_LAUNCH == 'true':
        # API模式，需要自动启动comfyui进程
        print("Auto launch comfyui process...")
        run_comfyui_thread = threading.Thread(target=run_comfyui)
        run_comfyui_thread.start()

    run_agent_app(r.app)
