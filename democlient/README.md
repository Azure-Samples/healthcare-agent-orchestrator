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
VITE_API_BASE_URL=http://localhost:8000/api
```

Replace the URL with your backend API URL if different.

## Running the application

For development:
```bash
npm run dev
```

For production build:
```bash
npm run build
```

To preview the production build:
```bash
npm run preview
```

The development server will be available at http://localhost:3000.

## Features

- Create new chat sessions
- Send messages to agents
- View agent responses
- Agent mention support with @ syntax
- Markdown rendering for agent responses

## Build System

This project uses Vite as the build tool, which provides:
- Fast development server with Hot Module Replacement (HMR)
- Optimized production builds
- Native ES modules support
- TypeScript support out of the box

## Troubleshooting

If you encounter issues:

1. Make sure the backend API is running and accessible
2. Check browser console for any error messages
3. Verify that authentication is properly configured
4. Check network requests to see if API calls are succeeding
5. Ensure Node.js version is compatible (>=18.0.0 recommended)

## Migration from Create React App

This project has been migrated from Create React App to Vite for better performance and development experience. Key changes:
- Environment variables now use `VITE_` prefix instead of `REACT_APP_`
- Faster development server and build times
- Native ES modules support
