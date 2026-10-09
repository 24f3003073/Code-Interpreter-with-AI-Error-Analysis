# Code Interpreter with AI Error Analysis

## Files
- `main.py`: FastAPI app with `POST /code-interpreter` and `GET /` health route.
- `requirements.txt`: Python dependencies.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set AIPIPE_TOKEN in your shell environment before starting the server.
uvicorn main:app --reload --port 8000
```

Test successful execution:
```bash
curl -X POST http://127.0.0.1:8000/code-interpreter \
  -H 'Content-Type: application/json' \
  -d '{"code":"x = 5\ny = 10\nprint(x + y)"}'
```
Expected: `{"error":[],"result":"15\n"}`

Test an error:
```bash
curl -X POST http://127.0.0.1:8000/code-interpreter \
  -H 'Content-Type: application/json' \
  -d '{"code":"x = 10\ny = 0\nresult = x / y"}'
```

## Deploy on Render
1. Push `main.py` and `requirements.txt` to a GitHub repository.
2. In Render, create a **Web Service** connected to that repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variable `AIPIPE_TOKEN` with your own AI Pipe token in Render's environment settings. Never commit the token to Git.
6. Wait for deployment. Test `https://YOUR-SERVICE.onrender.com/`.
7. Submit `https://YOUR-SERVICE.onrender.com/code-interpreter` in the assignment.

## Important security note
This is an educational prototype, not a secure multi-tenant code sandbox. Running arbitrary Python can still access the host's filesystem or network from the child process. Do not expose it to untrusted users in a real production service without OS/container isolation, resource limits, and a stricter security design.
