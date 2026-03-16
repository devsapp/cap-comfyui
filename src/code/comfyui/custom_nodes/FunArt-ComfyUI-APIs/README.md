# ComfyUI-FunArt-APIs

FunArt's built-in third-party API

> [!NOTE]
> This projected was created with a [cookiecutter](https://github.com/Comfy-Org/cookiecutter-comfy-extension) template. It helps you start writing custom nodes without worrying about the Python setup.

## Quickstart

### Installation Steps

#### Closed Source Installation (Current)

1. **Download the zip source package** from the internal GitLab repository

2. **Delete the old plugin** (if exists)
   - Navigate to FunArt's file management interface
   - Delete the existing `ComfyUI-FunArt-APIs` directory under `custom_nodes/`

3. **Upload and extract the source package**
   - Use FunArt's file management to upload the zip file
   - Extract it to the `custom_nodes/` directory

4. **Rename the extracted directory**
   - Locate the extracted directory (named `funart-plugins-${branchName}-${commitID}`)
   - Rename it to `ComfyUI-FunArt-APIs`

5. **Install dependencies**
   ```bash
   cd ~/comfyui/custom_nodes/ComfyUI-FunArt-APIs
   pip install -r requirements.txt
   ```

6. **Restart ComfyUI**
   - Restart ComfyUI via FunArt's control panel or ComfyUI-Manager

---

#### Open Source Installation (Deprecated)

> [!WARNING]
> This installation method is deprecated and kept for reference only.

1. Log in to your ComfyUI instance

2. Navigate to the custom_nodes directory
   ```bash
   cd ~/comfyui/custom_nodes
   ```

3. Clone this repository
   ```bash
   git clone <repository-url>
   cd ComfyUI-FunArt-APIs
   ```

4. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```

5. Restart ComfyUI
   - Restart ComfyUI via ComfyUI-Manager
   - Or manually restart the ComfyUI service

### Usage Examples

After installation, you can import and use the example workflows from the `workflows/` directory:

- `Wan2_5_I2V/` - Image-to-Video example
- `Wan2_5_T2V/` - Text-to-Video example
- `Wan2_5_T2I/` - Text-to-Image example
- `Wan2_5_ImageEdit/` - Image editing example

### API Key Configuration

Two methods are supported for configuring the DashScope API Key:

1. **Configure in workflow nodes**: Fill in the `api_key` parameter directly in the node
2. **Use environment variable**: Set the environment variable `DASHSCOPE_API_KEY`

The key configured in the workflow takes priority; if not configured, the environment variable will be used.

# Features

- A list of features

## Develop

To install the dev dependencies and pre-commit (will run the ruff hook), do:

```bash
pip install -e ".[dev]"
pre-commit install
```

The `-e` flag above will result in a "live" install, in the sense that any changes you make to your node extension will automatically be picked up the next time you run ComfyUI.

## Publish to Github

Install Github Desktop or follow these [instructions](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent) for ssh.

1. Create a Github repository that matches the directory name. 
2. Push the files to Git
```
git add .
git commit -m "project scaffolding"
git push
``` 

## Writing custom nodes

An example custom node is located in [node.py](src/funart_apis/nodes.py). To learn more, read the [docs](https://docs.comfy.org/essentials/custom_node_overview).


## Tests

This repo contains unit tests written in Pytest in the `tests/` directory. It is recommended to unit test your custom node.

- [build-pipeline.yml](.github/workflows/build-pipeline.yml) will run pytest and linter on any open PRs
- [validate.yml](.github/workflows/validate.yml) will run [node-diff](https://github.com/Comfy-Org/node-diff) to check for breaking changes

## Publishing to Registry

If you wish to share this custom node with others in the community, you can publish it to the registry. We've already auto-populated some fields in `pyproject.toml` under `tool.comfy`, but please double-check that they are correct.

You need to make an account on https://registry.comfy.org and create an API key token.

- [ ] Go to the [registry](https://registry.comfy.org). Login and create a publisher id (everything after the `@` sign on your registry profile). 
- [ ] Add the publisher id into the pyproject.toml file.
- [ ] Create an api key on the Registry for publishing from Github. [Instructions](https://docs.comfy.org/registry/publishing#create-an-api-key-for-publishing).
- [ ] Add it to your Github Repository Secrets as `REGISTRY_ACCESS_TOKEN`.

A Github action will run on every git push. You can also run the Github action manually. Full instructions [here](https://docs.comfy.org/registry/publishing). Join our [discord](https://discord.com/invite/comfyorg) if you have any questions!

