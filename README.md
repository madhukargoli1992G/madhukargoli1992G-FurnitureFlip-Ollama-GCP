# FurnitureFlip – Ollama + GCP + Kubernetes

FurnitureFlip is a conversational AI-powered marketplace assistant that helps users
price and list used furniture by generating:

- Dynamic listing forms
- Comparable price analysis (comps)
- Pricing recommendations

## Architecture

- **Frontend**: Streamlit (chat UI)
- **Backend**: FastAPI (intent detection, form + pricing logic)
- **LLM**: Ollama (local model inside Kubernetes)
- **Search**: Google Programmable Search Engine (CSE)
- **Infra**: Google Kubernetes Engine (GKE)

## Repository Structure

backend/ # FastAPI backend
frontend/ # Streamlit UI
k8s/ # Kubernetes manifests
ollama/ # Ollama Docker setup
query/ # Utility scripts


## How It Works

1. User chats with the app (e.g. "I want to sell a chair")
2. Backend detects intent and extracts details
3. Comparable listings are fetched
4. Price recommendations are generated
5. UI renders comps, charts, and next steps

## Status

🚧 Experimental / learning project  
Built to explore:
- LLM agents
- Kubernetes deployments
- Real-world pricing workflows

---

## Author

**Madhukar Goli**

