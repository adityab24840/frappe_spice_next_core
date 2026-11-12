# Card OCR training backend

A small stdlib HTTP service that runs wherever PyTorch lives (not inside the Frappe bench) and trains readers with Card Studio's trainer.

    export OCR_BACKEND_TOKEN='<a long random secret>'
    export STUDIO_DIR=/path/to/banglahandwriting/studio      # the folder that holds trainer.py
    python -m spice_next_core.card_ocr.backend.server --port 8790     # needs the Python that has torch, onnxruntime, tensorflow (optional)
    # or: python server.py --port 8790   (from this folder; it only needs the standard library itself)

Then in Frappe, open **OCR Settings** and set the backend URL (`http://127.0.0.1:8790`) and the same token.

- Frappe builds a bundle (labels, crops, template, grid, writer codes) from people-checked labels only, posts it to `/train`, polls `/status/<job>`,
  and imports the finished pack as a **Draft** OCR Card Pack. A pack trained on unverified machine reads cannot be marked Shipped.
- The card is installed into Studio's folders as `fr_<card key>`, so it can never overwrite one of Studio's own cards. One run at a time.
- Binds to 127.0.0.1 by default. Every request except `/health` needs the `X-OCR-Token` header. Do not expose it beyond the machine or private network
  that Frappe runs on: it accepts training data.
- Bundle contents are checked strictly: exact member names, no path traversal, size caps, writer codes never names.
