#!/bin/bash

# Script to generate PNG images from all DrawIO files
# Usage: ./generate_pngs.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if drawio command is available
if ! command -v drawio &> /dev/null; then
    echo "Error: drawio command not found. Please install draw.io desktop application."
    echo "Download from: https://github.com/jgraph/drawio-desktop/releases"
    exit 1
fi

echo "Generating PNG images from DrawIO files..."

# Find all .drawio files and convert them to PNG
for drawio_file in *.drawio; do
    if [ -f "$drawio_file" ]; then
        png_file="${drawio_file%.drawio}.png"
        echo "Converting $drawio_file -> $png_file"
        
        # Convert drawio to PNG
        drawio --export --format png --output "$png_file" "$drawio_file"
        
        if [ $? -eq 0 ]; then
            echo "✓ Successfully generated $png_file"
        else
            echo "✗ Failed to generate $png_file"
        fi
    fi
done

echo "PNG generation complete!"