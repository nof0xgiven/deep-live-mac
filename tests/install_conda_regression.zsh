#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_PATH="$ROOT_DIR/deep_live_cam.sh"
TMP_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

export HOME="$TMP_DIR/home"
mkdir -p "$HOME"
export ZDOTDIR="$HOME"
touch "$HOME/.zshenv"
touch "$HOME/.zshrc"

FAKE_BIN="$TMP_DIR/bin"
TEST_CONDA_BIN="$TMP_DIR/miniconda/base/bin"
mkdir -p "$FAKE_BIN"

cat > "$FAKE_BIN/brew" <<'EOF'
#!/bin/zsh
set -euo pipefail

if [[ "$*" == "install --cask miniconda" ]]; then
    mkdir -p "$TEST_CONDA_BIN"
    cat > "$TEST_CONDA_BIN/conda" <<'INNER'
#!/bin/zsh
exit 0
INNER
    chmod +x "$TEST_CONDA_BIN/conda"
    exit 0
fi

echo "unexpected brew invocation: $*" >&2
exit 1
EOF
chmod +x "$FAKE_BIN/brew"

cat > "$FAKE_BIN/conda" <<'EOF'
#!/bin/zsh
exit 0
EOF
chmod +x "$FAKE_BIN/conda"

export PATH="$FAKE_BIN:/usr/bin:/bin"
export TEST_CONDA_BIN

eval "$(
    awk '
        /^ENV_NAME=/ || /^REQUIRED_PYTHON_VERSION=/ || /^BREW_CONDA_PATH[12]=/ { print }
        /^check_conda\(\)/,/^}/ { print }
        /^install_conda\(\)/,/^}/ { print }
    ' "$SCRIPT_PATH"
)"

BREW_CONDA_PATH1="$TEST_CONDA_BIN"
BREW_CONDA_PATH2="$TMP_DIR/intel-miniconda/base/bin"
CONDA_BIN_PATH=""

install_conda

if [[ "$CONDA_BIN_PATH" != "$TEST_CONDA_BIN" ]]; then
    echo "Expected CONDA_BIN_PATH to be '$TEST_CONDA_BIN', got '${CONDA_BIN_PATH:-<empty>}'" >&2
    exit 1
fi

if [[ ! -x "$CONDA_BIN_PATH/conda" ]]; then
    echo "Expected executable conda at '$CONDA_BIN_PATH/conda'" >&2
    exit 1
fi
