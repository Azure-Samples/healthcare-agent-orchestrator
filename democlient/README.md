# Healthcare Agent Orchestrator Chat Client

This is a React-based frontend for the Healthcare Agent Orchestrator. It allows users to interact with the agents through a web interface instead of using Microsoft Teams.

## Setup

1. Install dependencies:
```bash
npm install
```

2. Configure environment variables (optional):
Create a `.env` file in the root directory with the following content:
```
REACT_APP_API_BASE_URL=http://localhost:8000/api
```

Replace the URL with your backend API URL if different.

## Running the application

```bash
npm start
```

The application will be available at http://localhost:3000.

## Features

- Create new chat sessions
- Send messages to agents
- View agent responses

## Troubleshooting

If you encounter issues:

1. Make sure the backend API is running and accessible
2. Check browser console for any error messages
3. Verify that authentication is properly configured
4. Check network requests to see if API calls are succeeding