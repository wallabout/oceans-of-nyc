"""Minimal Modal test to verify basic functionality."""

import modal

app = modal.App("test-hello")

image = modal.Image.debian_slim(python_version="3.12")


@app.function(image=image)
def hello(name: str):
    return f"Hello, {name}!"


@app.local_entrypoint()
def main():
    result = hello.remote("World")
    print(result)
