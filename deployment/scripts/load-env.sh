#!/bin/bash
# Safely load environment variables from .env file
# Handles JSON values and special characters properly

if [ ! -f .env ]; then
    echo "Error: .env file not found"
    return 1
fi

# Read .env file line by line
while IFS= read -r line || [ -n "$line" ]; do
    # Skip empty lines
    [[ -z "$line" ]] && continue
    
    # Skip comments
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    
    # Remove leading/trailing whitespace
    line=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    
    # Skip if empty after trimming
    [[ -z "$line" ]] && continue
    
    # Export the variable
    export "$line"
done < .env

