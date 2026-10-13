# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from pathlib import Path

block_cipher = None

# Paths
repo_root = Path(os.path.abspath(os.getcwd()))
src_path = repo_root / 'src'
static_path = repo_root / 'src' / 'eternix' / 'static'

# llama.cpp binaries
llama_bin = repo_root / 'build' / 'llama.cpp' / 'bin'

a = Analysis(
    ['src/eternix/cli/main.py'],
    pathex=[str(src_path)],
    binaries=[],
    datas=[
        (str(static_path), 'eternix/static'),
        (str(repo_root / 'README.md'), '.'),
        (str(repo_root / '.env'), '.'),
        (str(llama_bin), 'eternix/build/llama.cpp/bin'),
    ],
    hiddenimports=[
        'eternix.api.server',
        'eternix.auth',
        'eternix.auth.config',
        'eternix.auth.models',
        'eternix.cli.main',
        'eternix.core.config',
        'eternix.core.models',
        'eternix.core.orchestrator',
        'eternix.core.task_store',
        'eternix.core.langgraph_orchestrator',
        'eternix.core.events',
        'eternix.memory',
        'eternix.tools.registry',
        'eternix.tools.filesystem',
        'eternix.tools.command',
        'eternix.tools.coding',
        'eternix.tools.document',
        'eternix.tools.data',
        'eternix.tools.web',
        'eternix.tools.memory',
        'eternix.tools.vision',
        'eternix.tools.audio',
        'eternix.tools.generation',
        'eternix.tools.workspace',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'langgraph',
        'langchain_core',
        'tree_sitter',
        'tree_sitter_languages',
        'ddgs',
        'trafilatura',
        'apscheduler',
        'mcp',
        'qdrant_client',
        'fastembed',
        'sentence_transformers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='eternix',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='eternix',
)
