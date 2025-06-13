#!/bin/bash
# Build script for the React frontend

set -e # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEMOCLIENT_DIR="$PROJECT_ROOT/democlient"
SRC_DIR="$DEMOCLIENT_DIR/src"
BUILD_DIR="$DEMOCLIENT_DIR/build"
STATIC_DIR="$PROJECT_ROOT/src/static"

# Get environment values
echo "Getting environment variables from azd..."
eval "$(azd env get-values)"

# Check if frontend build is disabled
if [ "$DISABLE_FRONT_END" = "true" ]; then
    echo "Frontend build is disabled (DISABLE_FRONT_END=true). Skipping frontend build."
    exit 0
fi

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "Node.js is required for frontend build but not installed."
    read -p "Do you want to skip the frontend build? (y/n) " skipFrontend
    if [ "$skipFrontend" = "y" ] || [ "$skipFrontend" = "Y" ]; then
        echo "Skipping frontend build. Note that the application may not function properly without a built frontend."
        exit 0
    else
        echo "Please install Node.js and try again."
        exit 1
    fi
fi

# Navigate to the democlient directory
cd "$DEMOCLIENT_DIR"

# Check if env file exists and get its content
ENV_FILE=".env.production"
ENV_FILE_CHANGED=1

if [ -f "$ENV_FILE" ]; then
    EXISTING_ENV_CONTENT=$(cat "$ENV_FILE")
    NEW_ENV_CONTENT="REACT_APP_API_BASE_URL=/api"
    
    if [ "$EXISTING_ENV_CONTENT" = "$NEW_ENV_CONTENT" ]; then
        echo "Environment file exists and content is unchanged."
        ENV_FILE_CHANGED=0
    else
        echo "Environment file content has changed."
    fi
fi

# Create environment file for React if needed
if [ "$ENV_FILE_CHANGED" -eq 1 ]; then
    echo "Creating or updating $ENV_FILE file..."
    cat > $ENV_FILE << EOL
REACT_APP_API_BASE_URL=/api
EOL
fi

# Function to check if build is needed
need_rebuild() {
    local force="$1"
    local env_changed="$2"
    
    # Always build if the --force flag is passed
    if [ "$force" == "--force" ]; then
        echo "Force rebuild requested."
        return 0
    fi

    # Always build if build directory doesn't exist
    if [ ! -d "$BUILD_DIR" ]; then
        echo "Build directory doesn't exist. Build needed."
        return 0
    fi

    # Check if any source files are newer than the build directory
    if [ -n "$(find "$SRC_DIR" -type f -newer "$BUILD_DIR" 2>/dev/null)" ]; then
        echo "Source files have changed. Build needed."
        return 0
    fi

    # Check if package-lock.json is newer than build directory
    if [ -f "package-lock.json" ] && [ "package-lock.json" -nt "$BUILD_DIR" ]; then
        echo "package-lock.json has changed. Build needed."
        return 0
    fi
    
    # Check if env file has changed
    if [ "$env_changed" -eq 1 ]; then
        echo "Environment file has changed. Build needed."
        return 0
    fi

    echo "No changes detected. Skipping build."
    return 1
}

# Install dependencies if needed
if [ ! -d "node_modules" ] || [ "$1" == "--force" ]; then
    echo "Installing dependencies from package-lock.json..."
    npm ci
fi

# Check if we need to rebuild
if need_rebuild "$1" "$ENV_FILE_CHANGED"; then
    # Build the React app
    echo "Building React app..."
    npm run build
    echo "Frontend build completed successfully!"
else
    echo "Using existing build."
fi

# Copy the build directory to src/static for deployment
echo "Copying build files to src/static directory for deployment..."
mkdir -p "$STATIC_DIR"
rm -rf "$STATIC_DIR"/*
cp -R "$BUILD_DIR"/* "$STATIC_DIR"/
cp -R "$BUILD_DIR/static" "$STATIC_DIR"/
echo "Files copied successfully!" 