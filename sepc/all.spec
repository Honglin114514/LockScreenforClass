# -*- mode: python ; coding: utf-8 -*-

# ========== lsc 的 Analysis ==========
a_analysis = Analysis(
    ['D:\\python文件\\LAZY-CLS\\Lock Screen for Class\\lockscreenforclass.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

a_pyz = PYZ(a_analysis.pure)

a_exe = EXE(
    a_pyz,
    a_analysis.scripts,
    [],
    exclude_binaries=True,   # 只保留一次
    name='lockscreenforclass',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ========== setting 的 Analysis ==========
b_analysis = Analysis(
    ['setting.py'],
    pathex=[],
    binaries=[
        (r'C:\Users\27106\AppData\Local\Programs\Python\Python39\Lib\site-packages\PyQt5\Qt5\bin\QtWebEngineProcess.exe', '.')
    ],
    datas=[
        ('setting.html', '.'),
        ('themes', 'themes'),
        ('qt.conf', '.'),
    ],
    hiddenimports=[
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtWebChannel'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

b_pyz = PYZ(b_analysis.pure)

b_exe = EXE(
    b_pyz,
    b_analysis.scripts,
    b_analysis.binaries,
    b_analysis.datas,
    [],
    name='setting',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    exclude_binaries=True,   # 只保留一次
)

# ========== 唯一的 COLLECT：合并所有依赖 ==========
coll = COLLECT(
    a_exe,
    a_analysis.binaries,
    a_analysis.datas,
    b_exe,
    b_analysis.binaries,
    b_analysis.datas,
    strip=False,
    upx=True,
    name='test',
)