#!/usr/bin/env bash

ACTION="${1:-help}"

RUNTIME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/runtime" && pwd)"

if [[ ! -d "$RUNTIME_DIR" ]]; then
    echo "Error: runtime directory not found at $RUNTIME_DIR" >&2
    exit 1
fi

cd "$RUNTIME_DIR" || exit 1

case "$ACTION" in
    test)
        echo "Running tests in runtime module..."
        cargo test
        ;;

    build)
        echo "Building WASM module via wasm-pack..."
        wasm-pack build --target web
        ;;

    serve)
        echo "Starting local HTTP server on port 8000..."
        python -m http.server 8000
        ;;

    all)
        echo "Running tests..."
        if cargo test; then
            echo "Building WASM module..."
            wasm-pack build --target web
        else
            echo "Tests failed. Skipping build." >&2
            exit 1
        fi
        ;;

    *)
        echo "Usage: ./run.sh [Action]"
        echo "Actions:"
        echo "  test  - Run cargo tests"
        echo "  build - Build WASM module via wasm-pack"
        echo "  all   - Run tests and build WASM module"
        echo "  serve - Start python HTTP server to test WASM"
        ;;
esac

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1