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
touch "$HOME/.zshenv" "$HOME/.zshrc" "$HOME/.zprofile"

load_installer_functions() {
    eval "$(
        awk '
            NR == 1 { print }
            /^# Constants/, /^PYTHON_PARAMS=/ { print }
            /^check_and_install_homebrew\(\)/,/^}/ { print }
            /^clone_repo\(\)/,/^}/ { print }
            /^verify_file_sha256\(\)/,/^}/ { print }
            /^download_verified_file\(\)/,/^}/ { print }
            /^ensure_verified_model\(\)/,/^}/ { print }
            /^check_and_download_models\(\)/,/^}/ { print }
        ' "$SCRIPT_PATH"
    )"
}

sha256_text() {
    printf "%s" "$1" | shasum -a 256 | awk '{print $1}'
}

test_homebrew_bootstrap_does_not_execute_remote_script() {
    local case_dir="$TMP_DIR/homebrew"
    local fake_bin="$case_dir/bin"
    mkdir -p "$fake_bin"

    cat > "$fake_bin/curl" <<'EOF'
#!/bin/zsh
echo "remote script should not be fetched" >&2
exit 99
EOF
    chmod +x "$fake_bin/curl"

    PATH="$fake_bin:/usr/bin:/bin"
    load_installer_functions

    set +e
    ( check_and_install_homebrew ) >"$case_dir/out" 2>"$case_dir/err"
    local exit_status=$?
    set -e

    if [[ "$exit_status" -eq 0 ]]; then
        echo "Expected missing Homebrew to fail closed instead of executing remote bootstrap." >&2
        return 1
    fi
    if grep -q "remote script should not be fetched" "$case_dir/err"; then
        echo "Expected Homebrew bootstrap path not to invoke curl." >&2
        return 1
    fi
}

test_clone_repo_uses_bundled_source_without_git() {
    local case_dir="$TMP_DIR/bundled-source"
    local fake_bin="$case_dir/bin"
    mkdir -p "$fake_bin" "$case_dir/Deep-Live-Cam"
    touch "$case_dir/Deep-Live-Cam/run.py"

    cat > "$fake_bin/git" <<'EOF'
#!/bin/zsh
echo "git should not be invoked for bundled source" >&2
exit 1
EOF
    chmod +x "$fake_bin/git"

    (
        cd "$case_dir"
        PATH="$fake_bin:/usr/bin:/bin"
        load_installer_functions
        clone_repo
    )
}

test_clone_repo_rejects_missing_bundled_source() {
    local case_dir="$TMP_DIR/missing-bundled-source"
    mkdir -p "$case_dir"

    set +e
    (
        cd "$case_dir"
        load_installer_functions
        clone_repo >out 2>err
    )
    local exit_status=$?
    set -e
    if [[ "$exit_status" -eq 0 ]]; then
        echo "Expected clone_repo to fail when bundled app source is missing." >&2
        return 1
    fi
}

test_model_download_rejects_digest_mismatch() {
    local case_dir="$TMP_DIR/models"
    local fake_bin="$case_dir/bin"
    mkdir -p "$fake_bin"

    cat > "$fake_bin/curl" <<'EOF'
#!/bin/zsh
set -euo pipefail
local output=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o)
            output="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done
printf "tampered" > "$output"
EOF
    chmod +x "$fake_bin/curl"

    set +e
    (
        cd "$case_dir"
        PATH="$fake_bin:/usr/bin:/bin"
        load_installer_functions
        MODELS_DIR="$case_dir/Deep-Live-Cam/models"
        MODEL_1="$MODELS_DIR/GFPGANv1.4.pth"
        MODEL_2="$MODELS_DIR/inswapper_128_fp16.onnx"
        MODEL_1_SHA256="$(sha256_text expected-gfpgan)"
        MODEL_2_SHA256="$(sha256_text expected-inswapper)"
        check_and_download_models >out 2>err
    )
    local exit_status=$?
    set -e
    if [[ "$exit_status" -eq 0 ]]; then
        echo "Expected model download with a digest mismatch to fail." >&2
        return 1
    fi
}

test_existing_model_rejects_digest_mismatch() {
    local case_dir="$TMP_DIR/existing-model"
    mkdir -p "$case_dir/Deep-Live-Cam/models"

    set +e
    (
        cd "$case_dir"
        load_installer_functions
        MODELS_DIR="$case_dir/Deep-Live-Cam/models"
        MODEL_1="$MODELS_DIR/GFPGANv1.4.pth"
        MODEL_2="$MODELS_DIR/inswapper_128_fp16.onnx"
        MODEL_1_SHA256="$(sha256_text expected-gfpgan)"
        MODEL_2_SHA256="$(sha256_text expected-inswapper)"
        printf "tampered" > "$MODEL_1"
        printf "expected-inswapper" > "$MODEL_2"

        check_and_download_models >out 2>err
    )
    local exit_status=$?
    set -e
    if [[ "$exit_status" -eq 0 ]]; then
        echo "Expected existing model with a digest mismatch to fail." >&2
        return 1
    fi
}

test_homebrew_bootstrap_does_not_execute_remote_script
test_clone_repo_uses_bundled_source_without_git
test_clone_repo_rejects_missing_bundled_source
test_model_download_rejects_digest_mismatch
test_existing_model_rejects_digest_mismatch
