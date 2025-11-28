# Temporal Research UI - Developer Integration Guide

## Overview

This UI connects to the Temporal Interactive Research Workflow. The frontend is complete and ready - developers need to uncomment and configure the Temporal integration in `backend/main.py`.

## Quick Start

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure Environment

**Connect to cloud**
Setup your cloud configuration profile in `temporal.toml` under the `profile.cloud` TOML header:

```toml
[profile.cloud]
address = "your-namespace.tmprl.cloud:7233"
namespace = "your-namespace"
api_key = "your-api-key" 

[profile.cloud.tls]
# TLS is auto-enabled when api_key is present
```

Set the `TEMPORAL_PROFILE` environment variable to `cloud`.

Read more about our environment configuration [in our docs!](https://docs.temporal.io/develop/environment-configuration)

**Run locally**
No need to change your environment!

### 3. Enable Temporal Integration

Open `backend/main.py` and:

1. **Uncomment the imports** (lines 58-82)
2. **Uncomment `get_temporal_client()`** (lines 85-94)
3. **Uncomment the implementation** in each endpoint (the TODO blocks)
4. **Remove the `raise HTTPException`** lines

### 4. Run the Server

```bash
python main.py
```

or

```bash
uv run backend/main.py
```

Server runs at: `http://localhost:8233`

## API Contract

The frontend expects these exact response shapes:

### POST /api/start-research

**Request:**
```json
{
  "query": "User's research question"
}
```

**Response:**
```json
{
  "workflow_id": "interactive-research-abc123",
  "status": "started"
}
```

### GET /api/status/{workflow_id}

**Response (awaiting clarifications):**
```json
{
  "workflow_id": "interactive-research-abc123",
  "status": "awaiting_clarifications",
  "current_question": "What aspects interest you most?",
  "current_question_index": 0,
  "total_questions": 3
}
```

**Response (researching):**
```json
{
  "workflow_id": "interactive-research-abc123",
  "status": "researching"
}
```

**Response (complete):**
```json
{
  "workflow_id": "interactive-research-abc123",
  "status": "complete"
}
```

### POST /api/answer/{workflow_id}

**Request:**
```json
{
  "answer": "User's answer to clarification"
}
```

**Response:**
```json
{
  "status": "accepted",
  "workflow_status": "awaiting_clarifications",
  "questions_remaining": 2
}
```

### GET /api/result/{workflow_id}

**Response:**
```json
{
  "workflow_id": "interactive-research-abc123",
  "markdown_report": "# Research Report\n\n## Summary\n...",
  "short_summary": "Brief summary of findings",
  "follow_up_questions": [
    "Would you like more detail on X?",
    "Should we explore Y?"
  ]
}
```

## Workflow Status Values

The frontend handles these status values:

| Status | Frontend Behavior |
|--------|-------------------|
| `awaiting_clarifications` | Shows `current_question` as bot message |
| `researching` | Shows spinner with "Researching..." |
| `complete` | Fetches result, redirects to success.html |

## Frontend Files

| File | Purpose |
|------|---------|
| `index.html` | Chat interface (entry point) |
| `success.html` | Results display with accordion |
| `api-client.js` | JavaScript API wrapper |

## Frontend Configuration

To change the API URL, edit `index.html` line 264:

```javascript
const API_BASE_URL = 'http://localhost:8233';
```

## Integration Checklist

- [ ] Uncomment Temporal imports in main.py
- [ ] Uncomment get_temporal_client() function
- [ ] Implement POST /api/start-research
- [ ] Implement GET /api/status/{workflow_id}
- [ ] Implement POST /api/answer/{workflow_id}
- [ ] Implement GET /api/result/{workflow_id}
- [ ] Configure temporal.toml with Temporal connection
- [ ] Start Temporal server or connect to Cloud
- [ ] Start worker (uv run openai_agents/run_worker.py)
- [ ] Test full flow

## Testing Without Temporal

For UI testing without Temporal, you can:

1. Add mock responses directly in the endpoints
2. Use the mock version of index.html (available on request)

## File Structure

```
demo-output/
├── backend/
│   ├── main.py              # FastAPI server (configure here)
│   └── requirements.txt     # Python dependencies
├── index.html               # Chat UI
├── success.html             # Results page
├── api-client.js            # JS API client
├── styles.css               # Shared styles
├── *.otf                    # Aeonik fonts
└── *.svg                    # Icons
```

## Troubleshooting

### CORS Errors
CORS is configured to allow all origins. For production, update:
```python
allow_origins=["https://your-domain.com"]
```

### Connection Refused
- Check Temporal server is running
- Verify address in temporal.toml for your profile
- Check port 7233 is accessible

### Workflow Not Found
- Verify workflow_id is being passed correctly
- Check worker is running and registered

## Support

For issues with:
- **UI/Frontend**: Check browser console for errors
- **API/Backend**: Check FastAPI logs
- **Temporal**: Check worker logs and Temporal UI (localhost:8233)
