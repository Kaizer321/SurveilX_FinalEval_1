# module1/src/vector_store/clip_embedder.py
from typing import List
import numpy as np
from PIL import Image
import torch
from transformers import CLIPProcessor, CLIPModel

# Hugging Face CLIP model (image encoder)
_MODEL_NAME = "openai/clip-vit-base-patch32"
_device = "cuda" if torch.cuda.is_available() else "cpu"
_model = None
_processor = None


def _get_clip():
    global _model, _processor
    if _model is None or _processor is None:
        _model = CLIPModel.from_pretrained(_MODEL_NAME).to(_device)
        # Prefer fast processor if available to avoid deprecation warnings
        _processor = CLIPProcessor.from_pretrained(_MODEL_NAME, use_fast=True)
        _model.eval()
    return _model, _processor


def embed_image_bgr(frame_bgr: np.ndarray) -> List[float]:
    """Compute a CLIP embedding for an OpenCV BGR image (H,W,3 uint8).
    Returns a Python list[float] suitable for ChromaDB.
    """
    # Convert BGR -> RGB and to PIL
    rgb = frame_bgr[:, :, ::-1]
    pil = Image.fromarray(rgb)

    model, processor = _get_clip()
    with torch.no_grad():
        inputs = processor(images=pil, return_tensors="pt").to(_device)
        feats = model.get_image_features(**inputs)
        feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
    return feats.detach().cpu().numpy().flatten().astype(float).tolist()
