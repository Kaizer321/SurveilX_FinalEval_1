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


# Expose init_clip public function
def init_clip():
    global _model, _processor
    if _model is None or _processor is None:
        import os
        from pathlib import Path
        import transformers
        
        # Suppress warnings
        transformers.logging.set_verbosity_error()
        os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        
        # Check local models directory first
        local_model_path = Path("models/clip-vit-base-patch32")
        model_source = _MODEL_NAME
        
        if local_model_path.exists():
            print(f"Loading CLIP model from local path: {local_model_path}")
            model_source = str(local_model_path)
        else:
            print(f"Local CLIP model not found at {local_model_path}. Loading from Hugging Face: {_MODEL_NAME}")

        try:
            _model = CLIPModel.from_pretrained(model_source).to(_device)
            # Prefer fast processor if available to avoid deprecation warnings
            _processor = CLIPProcessor.from_pretrained(model_source, use_fast=True)
            _model.eval()
            print("CLIP model loaded successfully.")
        except Exception as e:
            print(f"Error loading CLIP model: {e}")
            if model_source != _MODEL_NAME:
                print(f"Falling back to online model: {_MODEL_NAME}")
                try:
                    _model = CLIPModel.from_pretrained(_MODEL_NAME).to(_device)
                    _processor = CLIPProcessor.from_pretrained(_MODEL_NAME, use_fast=True)
                    _model.eval()
                    print("CLIP model loaded from online source.")
                except Exception as e2:
                    print(f"Critical error loading fallback model: {e2}")
                    raise e2
            else:
                raise e

    return _model, _processor


def embed_image_bgr(frame_bgr: np.ndarray) -> List[float]:
    """Compute a CLIP embedding for an OpenCV BGR image (H,W,3 uint8).
    Returns a Python list[float] suitable for ChromaDB.
    """
    # Convert BGR -> RGB and to PIL
    rgb = frame_bgr[:, :, ::-1]
    pil = Image.fromarray(rgb)

    model, processor = init_clip()
    with torch.no_grad():
        inputs = processor(images=pil, return_tensors="pt").to(_device)
        feats = model.get_image_features(**inputs)
        
        # Handle case where return value is not a raw tensor (e.g. ModelOutput)
        if not isinstance(feats, torch.Tensor):
            if hasattr(feats, 'image_embeds'):
                feats = feats.image_embeds
            elif hasattr(feats, 'pooler_output'):
                feats = feats.pooler_output
        
        # Normalize features
        feats = torch.nn.functional.normalize(feats, p=2, dim=-1)
    return feats.detach().cpu().numpy().flatten().astype(float).tolist()


def embed_text(query: str) -> List[float]:
    """Compute a CLIP embedding for a text query.
    Returns a Python list[float] suitable for ChromaDB similarity search.
    """
    model, processor = init_clip()
    with torch.no_grad():
        inputs = processor(text=[query], return_tensors="pt", padding=True, truncation=True).to(_device)
        feats = model.get_text_features(**inputs)
        
        # Handle case where return value is not a raw tensor (e.g. ModelOutput)
        if not isinstance(feats, torch.Tensor):
            if hasattr(feats, 'text_embeds'):
                feats = feats.text_embeds
            elif hasattr(feats, 'pooler_output'):
                feats = feats.pooler_output
        
        # Normalize features
        feats = torch.nn.functional.normalize(feats, p=2, dim=-1)
    return feats.detach().cpu().numpy().flatten().astype(float).tolist()

