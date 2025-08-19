build-comfyui:
	cd ../../src/code/agent && docker build -t agent:latest .
	docker build --platform linux/amd64 -t comfyui:v1 .

deploy:
	s deploy --skip-push