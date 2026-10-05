# web_control.py
# 局域网 HTTP 控制模块
# - 提供网页 + JSON API
# - 锁定/解锁/关机/重启/toast 通过 main_queue 交给 Qt 主线程执行
# - 软件管理直接在 HTTP 线程执行，不经过主程序
# 所有失败只写日志，不影响主程序

import os
import json
import time
import queue
import logging
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# ============================================================
# 命令执行模块
# ------------------------------------------------------------
# 当前为同步实现：run() 阻塞到命令结束或超时，返回 task。
# 以后换异步：只需要替换 CommandRunner 的实现，
#             Handler / Server / 网页都不用动。
# ============================================================

_CMD_DECODE_ORDER = ("gbk", "utf-8", "cp936")


def _decode_bytes(b):
    if not b:
        return ""
    for enc in _CMD_DECODE_ORDER:
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("utf-8", errors="replace")


class CommandRunner:
    """命令执行器接口。当前是同步实现，后期可换异步实现，只要保持这些方法：
        run(cmd)          -> dict(task)   # 同步版会阻塞直到完成
        stop(task_id)     -> (ok, msg)
        get_history()     -> [dict(task)] # 最新在前
        get_task(task_id) -> dict(task) or None
    每个 task 字段：
        id, cmd, status(running/done/stopped/timeout/error),
        returncode, output, start_time, end_time
    """

    def run(self, cmd, timeout=30):
        raise NotImplementedError

    def stop(self, task_id):
        raise NotImplementedError

    def get_history(self):
        raise NotImplementedError

    def get_task(self, task_id):
        raise NotImplementedError


class SyncCommandRunner(CommandRunner):
    """同步实现：Popen + communicate(timeout)，保存句柄以支持 stop。"""

    def __init__(self, max_history=50, max_output=8192, default_timeout=30):
        self.max_history = max_history
        self.max_output = max_output
        self.default_timeout = default_timeout

        self._tasks = {}        # task_id -> dict
        self._order = []        # task_id，最新在前
        self._running = {}      # task_id -> Popen
        self._lock = threading.Lock()
        self._counter = 0

    # ---------- 内部工具 ----------
    def _new_id(self):
        with self._lock:
            self._counter += 1
            return f"t{self._counter}"

    def _trim_locked(self):
        while len(self._order) > self.max_history:
            old = self._order.pop()
            self._tasks.pop(old, None)

    def _creationflags(self):
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags |= subprocess.CREATE_NO_WINDOW
        return flags

    # ---------- 对外接口 ----------
    def run(self, cmd, timeout=None):
        if timeout is None:
            timeout = self.default_timeout

        task_id = self._new_id()
        task = {
            "id": task_id,
            "cmd": cmd,
            "status": "running",
            "returncode": None,
            "output": "",
            "start_time": time.time(),
            "end_time": None,
            "stop_requested": False,
        }
        with self._lock:
            self._tasks[task_id] = task
            self._order.insert(0, task_id)
            self._trim_locked()

        # 启动
        try:
            p = subprocess.Popen(
                ["cmd", "/c", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=self._creationflags(),
            )
        except Exception as e:
            logging.exception("命令启动失败")
            with self._lock:
                task["status"] = "error"
                task["output"] = f"启动失败: {e}"
                task["end_time"] = time.time()
            return task

        with self._lock:
            self._running[task_id] = p

        # 阻塞等待
        timed_out = False
        out_bytes = b""
        try:
            out_bytes, _ = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                    capture_output=True, timeout=5,
                    creationflags=self._creationflags(),
                )
            except Exception:
                logging.exception("超时 taskkill 失败")
            try:
                out_bytes, _ = p.communicate(timeout=3)
            except Exception:
                out_bytes = b""

        with self._lock:
            self._running.pop(task_id, None)

        text = _decode_bytes(out_bytes or b"")
        if len(text) > self.max_output:
            text = text[: self.max_output] + "\n……（输出已截断）"

        with self._lock:
            task["output"] = text
            task["end_time"] = time.time()
            if timed_out:
                task["status"] = "timeout"
            elif task.get("stop_requested"):
                task["status"] = "stopped"
            elif p.returncode is None:
                task["status"] = "error"
            else:
                task["status"] = "done"
                task["returncode"] = p.returncode
        return task

    def stop(self, task_id):
        with self._lock:
            p = self._running.get(task_id)
            task = self._tasks.get(task_id)
            if task is not None:
                task["stop_requested"] = True
        if not p:
            return False, "任务未在运行"
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                capture_output=True, timeout=5,
                creationflags=self._creationflags(),
            )
            return True, "已发送停止"
        except Exception as e:
            logging.exception("停止任务失败")
            return False, str(e)

    def get_history(self):
        with self._lock:
            return [dict(self._tasks[tid]) for tid in self._order
                    if tid in self._tasks]

    def get_task(self, task_id):
        with self._lock:
            t = self._tasks.get(task_id)
            return dict(t) if t else None

try:
    import psutil
except ImportError:
    psutil = None


# ============================================================
# 软件管理
# ============================================================

_SW_LOCKS_GUARD = threading.Lock()
_SW_LOCKS = {}


def _get_sw_lock(name):
    with _SW_LOCKS_GUARD:
        if name not in _SW_LOCKS:
            _SW_LOCKS[name] = threading.Lock()
        return _SW_LOCKS[name]


def _load_software_list(config_file):
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        items = cfg.get("software_list", [])
        if not isinstance(items, list):
            return []
        return items
    except Exception:
        logging.exception("读取 software_list 失败")
        return []


def _find_software(config_file, name):
    for item in _load_software_list(config_file):
        if item.get("name") == name:
            return item
    return None


def _is_running(process_name):
    if not process_name or psutil is None:
        return False
    try:
        target = process_name.lower()
        for p in psutil.process_iter(["name"]):
            try:
                n = p.info.get("name")
                if n and n.lower() == target:
                    return True
            except Exception:
                continue
    except Exception:
        logging.exception("扫描进程失败")
    return False


def _start_software(item):
    path = item.get("path", "")
    args = item.get("args", [])
    if not path:
        return False, "未配置 path"
    if not os.path.exists(path):
        return False, f"路径不存在: {path}"
    if not isinstance(args, list):
        args = []
    try:
        creationflags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            creationflags |= subprocess.DETACHED_PROCESS
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [path] + [str(a) for a in args],
            cwd=os.path.dirname(path) or None,
            creationflags=creationflags,
        )
        logging.info(f"启动软件: {item.get('name')}")
        return True, f"已启动 {item.get('name')}"
    except Exception as e:
        logging.exception("启动软件失败")
        return False, str(e)


def _stop_software(item):
    pname = item.get("process_name", "")
    if not pname:
        return False, "未配置 process_name"
    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        r = subprocess.run(
            ["taskkill", "/F", "/IM", pname, "/T"],
            capture_output=True, text=True, timeout=5,
            creationflags=creationflags,
        )
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode == 0:
            logging.info(f"停止软件: {item.get('name')}")
            return True, f"已停止 {item.get('name')}"
        else:
            logging.warning(f"停止软件失败({r.returncode}): {out}")
            return False, out or "taskkill 失败"
    except Exception as e:
        logging.exception("停止软件失败")
        return False, str(e)


def _restart_software(item):
    _stop_software(item)
    time.sleep(0.5)
    return _start_software(item)


# ============================================================
# 网页（手表端适配：大按钮、大字体、垂直布局）
# ============================================================

INDEX_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>锁屏控制</title>
<style>
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
html, body { margin: 0; padding: 0; }
body {
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    background: #0f0f1a;
    color: #fff;
    padding: 12px 12px 28px;
    font-size: 18px;
    -webkit-text-size-adjust: 100%;
}
.status {
    text-align: center;
    font-size: 20px;
    padding: 16px 10px;
    background: #1e1e2f;
    border-radius: 999px;
    margin-bottom: 14px;
    font-weight: bold;
}
.btn {
    display: block;
    width: 100%;
    padding: 26px 16px;
    font-size: 26px;
    font-weight: bold;
    border: none;
    border-radius: 999px;
    color: #fff;
    margin-bottom: 14px;
    font-family: inherit;
    line-height: 1.15;
    letter-spacing: 2px;
}
.btn:active { opacity: 0.6; }
.unlock   { background: #00aa66; }
.lock     { background: #cc3333; }
.shutdown { background: #aa3333; }
.reboot   { background: #aa6633; }
.toast-btn{ background: #3366cc; }
.run-btn  { background: #2266cc; }
.stop-btn { background: #cc3333; font-size: 20px; padding: 18px 12px; }
.refresh  { background: #444a5a; font-size: 20px; padding: 18px 12px; margin-bottom: 18px; }
.confirm-yes { background: #dd2222; font-size: 22px; padding: 22px 12px; }
.confirm-no  { background: #4a4a5a; font-size: 22px; padding: 22px 12px; }

input[type=text] {
    width: 100%;
    padding: 22px 20px;
    font-size: 22px;
    border-radius: 999px;
    border: none;
    margin-bottom: 14px;
    font-family: inherit;
    background: #fff;
    color: #000;
    text-align: center;
}
.section-title {
    font-size: 18px;
    color: #888;
    margin: 24px 6px 12px;
    font-weight: bold;
    letter-spacing: 1px;
}
.sw-item {
    background: #1e1e2f;
    border-radius: 22px;
    margin-bottom: 12px;
    overflow: hidden;
}
.sw-head {
    padding: 24px 22px;
    font-size: 22px;
    font-weight: bold;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    border-radius: 22px;
}
.sw-head:active { background: #2a2a40; }
.sw-status { font-size: 15px; white-space: nowrap; }
.sw-running { color: #00dd77; }
.sw-stopped { color: #888; }

.submenu {
    display: none;
    padding: 6px 12px 14px;
}
.submenu.open { display: block; }

.start   { background: #00aa66; font-size: 22px; padding: 22px 12px; }
.stop    { background: #cc3333; font-size: 22px; padding: 22px 12px; }
.restart { background: #aa6633; font-size: 22px; padding: 22px 12px; }

/* 命令历史 */
.cmd-history {
    background: #0a0a12;
    border-radius: 18px;
    padding: 10px;
    max-height: 50vh;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
}
.cmd-item {
    background: #181826;
    border-radius: 14px;
    padding: 12px 14px;
    margin-bottom: 10px;
}
.cmd-item:last-child { margin-bottom: 0; }
.cmd-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    font-size: 16px;
    font-weight: bold;
}
.cmd-name {
    font-family: Consolas, monospace;
    color: #b0d0ff;
    word-break: break-all;
    flex: 1;
}
.cmd-badge {
    font-size: 13px;
    padding: 4px 10px;
    border-radius: 999px;
    white-space: nowrap;
}
.badge-running { background: #2a4a7a; color: #9cf; }
.badge-done    { background: #1f5f3f; color: #7fe8b8; }
.badge-stopped { background: #5a3030; color: #ffa8a8; }
.badge-timeout { background: #5a4a20; color: #ffd58a; }
.badge-error   { background: #5a2030; color: #ff8a8a; }

.cmd-output {
    margin-top: 8px;
    font-family: Consolas, monospace;
    font-size: 13px;
    color: #d0d0d0;
    background: #06060c;
    border-radius: 10px;
    padding: 10px;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 32vh;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
}
.cmd-stop-row {
    margin-top: 8px;
}

#msg {
    text-align: center;
    font-size: 16px;
    color: #8af;
    min-height: 22px;
    margin: 16px 0 0;
    word-break: break-all;
}
</style>
</head>
<body>

<div class="status" id="status">状态加载中…</div>

<button class="btn refresh" onclick="refreshAll()">刷 新</button>

<button class="btn unlock" onclick="cmd('unlock')">解 锁</button>
<button class="btn lock"   onclick="cmd('lock')">锁 定</button>

<button class="btn shutdown" onclick="toggleMenu('shutdownMenu')">关 机</button>
<div class="submenu" id="shutdownMenu">
    <button class="btn confirm-yes" onclick="cmd('shutdown')">确认关机</button>
    <button class="btn confirm-no"  onclick="toggleMenu('shutdownMenu')">取消</button>
</div>

<button class="btn reboot" onclick="toggleMenu('rebootMenu')">重 启</button>
<div class="submenu" id="rebootMenu">
    <button class="btn confirm-yes" onclick="cmd('reboot')">确认重启</button>
    <button class="btn confirm-no"  onclick="toggleMenu('rebootMenu')">取消</button>
</div>

<input type="text" id="toastMsg" placeholder="广播内容" value="远程广播">
<button class="btn toast-btn" onclick="sendToast()">发送广播</button>

<div class="section-title">命令行</div>
<input type="text" id="cmdInput" placeholder="输入命令" autocomplete="off">
<button class="btn run-btn" onclick="runCmd()">执 行</button>
<div class="cmd-history" id="cmdHistory">加载中…</div>

<div class="section-title">软件管理</div>
<div id="swList">加载中…</div>

<div id="msg"></div>

<script>
function showMsg(t) { document.getElementById('msg').innerText = t || ''; }

function toggleMenu(id) {
    var el = document.getElementById(id);
    if (el) el.classList.toggle('open');
}

function closeAllMenus() {
    document.querySelectorAll('.submenu.open').forEach(function(el){
        el.classList.remove('open');
    });
}

function cmd(name) {
    closeAllMenus();
    fetch('/api/' + name, {method: 'POST'})
        .then(function(r){ return r.json(); })
        .then(function(d){ showMsg(d.message || 'ok'); refreshStatus(); })
        .catch(function(e){ showMsg('失败: ' + e); });
}

function sendToast() {
    var m = document.getElementById('toastMsg').value || '远程广播';
    fetch('/api/toast?msg=' + encodeURIComponent(m), {method: 'POST'})
        .then(function(r){ return r.json(); })
        .then(function(d){ showMsg(d.message || '已发送'); })
        .catch(function(e){ showMsg('失败: ' + e); });
}

function refreshStatus() {
    return fetch('/api/status')
        .then(function(r){ return r.json(); })
        .then(function(d){
            document.getElementById('status').innerText =
                d.locked ? '当前：已锁定' : '当前：未锁定';
        })
        .catch(function(){});
}

function refreshAll() {
    showMsg('刷新中…');
    refreshStatus();
    loadSoftware();
    loadHistory();
    setTimeout(function(){ showMsg('已刷新'); }, 300);
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function(c){
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
}

// ---------------- 软件管理 ----------------
function loadSoftware() {
    fetch('/api/software/list')
        .then(function(r){ return r.json(); })
        .then(function(d){
            var box = document.getElementById('swList');
            if (!d.software || d.software.length === 0) {
                box.innerText = '未配置软件';
                return;
            }
            var html = '';
            d.software.forEach(function(item){
                var st = item.running
                    ? '<span class="sw-status sw-running">● 运行中</span>'
                    : '<span class="sw-status sw-stopped">○ 未运行</span>';
                var name = escapeHtml(item.name);
                var nameAttr = escapeHtml(item.name);
                var id = 'sw_' + nameAttr.replace(/[^a-zA-Z0-9_]/g, '_');
                html +=
                    '<div class="sw-item">' +
                      '<div class="sw-head" onclick="toggleMenu(\'' + id + '\')">' +
                        '<span>' + name + '</span>' + st +
                      '</div>' +
                      '<div class="submenu" id="' + id + '">' +
                        '<button class="btn start"   onclick="swAction(\'start\',\''   + nameAttr + '\')">启 动</button>' +
                        '<button class="btn stop"    onclick="swAction(\'stop\',\''    + nameAttr + '\')">停 止</button>' +
                        '<button class="btn restart" onclick="swAction(\'restart\',\'' + nameAttr + '\')">重 启</button>' +
                      '</div>' +
                    '</div>';
            });
            box.innerHTML = html;
        })
        .catch(function(){});
}

function swAction(action, name) {
    closeAllMenus();
    showMsg('执行中…');
    fetch('/api/software/' + action + '?name=' + encodeURIComponent(name), {method: 'POST'})
        .then(function(r){ return r.json(); })
        .then(function(d){ showMsg(d.message || 'ok'); loadSoftware(); })
        .catch(function(e){ showMsg('失败: ' + e); });
}

// ---------------- 命令行 ----------------
function runCmd() {
    var input = document.getElementById('cmdInput');
    var c = (input.value || '').trim();
    if (!c) { showMsg('命令为空'); return; }
    showMsg('执行中…');
    fetch('/api/cmd/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cmd: c})
    })
    .then(function(r){ return r.json(); })
    .then(function(d){
        if (!d.success) { showMsg(d.message || '执行失败'); return; }
        showMsg('完成');
        input.value = '';
        loadHistory();
    })
    .catch(function(e){ showMsg('失败: ' + e); });
}

function loadHistory() {
    fetch('/api/cmd/history')
        .then(function(r){ return r.json(); })
        .then(function(d){ renderHistory(d.tasks || []); })
        .catch(function(){});
}

function badgeFor(status) {
    var map = {
        running: ['badge-running', '运行中'],
        done:    ['badge-done',    '完成'],
        stopped: ['badge-stopped', '已停止'],
        timeout: ['badge-timeout', '超时'],
        error:   ['badge-error',   '错误'],
    };
    var v = map[status] || ['badge-error', status];
    return '<span class="cmd-badge ' + v[0] + '">' + v[1] + '</span>';
}

function renderHistory(tasks) {
    var box = document.getElementById('cmdHistory');
    if (!tasks.length) { box.innerText = '暂无历史'; return; }
    var html = '';
    tasks.forEach(function(t){
        var out = escapeHtml(t.output || '');
        var stopRow = (t.status === 'running')
            ? '<div class="cmd-stop-row"><button class="btn stop-btn" ' +
              'onclick="stopCmd(\'' + escapeHtml(t.id) + '\')">停 止</button></div>'
            : '';
        html +=
            '<div class="cmd-item">' +
              '<div class="cmd-head">' +
                '<span class="cmd-name">' + escapeHtml(t.cmd) + '</span>' +
                badgeFor(t.status) +
              '</div>' +
              (out ? '<div class="cmd-output">' + out + '</div>' : '') +
              stopRow +
            '</div>';
    });
    box.innerHTML = html;
}

function stopCmd(id) {
    showMsg('停止中…');
    fetch('/api/cmd/stop', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: id})
    })
    .then(function(r){ return r.json(); })
    .then(function(d){ showMsg(d.message || 'ok'); loadHistory(); })
    .catch(function(e){ showMsg('失败: ' + e); });
}

// ---------------- 启动 ----------------
refreshStatus();
loadSoftware();
loadHistory();
</script>
</body>
</html>
"""


# ============================================================
# HTTP Handler
# ============================================================

class _Handler(BaseHTTPRequestHandler):
    command_runner = None   # 由 WebControlServer 注入
    config_file = ""
    main_queue = None

    def log_message(self, fmt, *args):
        logging.debug("[Web] " + (fmt % args))

    # ---------- 响应工具 ----------
    def _send_bytes(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(code, "application/json; charset=utf-8", body)

    def _send_html(self, html):
        self._send_bytes(200, "text/html; charset=utf-8", html.encode("utf-8"))

    # ---------- 主线程命令 ----------
    def _dispatch_main_cmd(self, cmd, params=None):
        if self.main_queue is None:
            return {"success": False, "message": "主程序未就绪"}
        result_q = queue.Queue()
        try:
            self.main_queue.put((cmd, params or {}, result_q))
        except Exception as e:
            logging.exception("放入主线程队列失败")
            return {"success": False, "message": str(e)}
        try:
            return result_q.get(timeout=5)
        except queue.Empty:
            return {"success": False, "message": "执行超时"}

    # ---------- 软件管理 ----------
    def _handle_software_list(self):
        try:
            items = _load_software_list(self.config_file)
            result = []
            for it in items:
                pname = it.get("process_name", "")
                result.append({
                    "name": it.get("name", ""),
                    "running": _is_running(pname),
                })
            self._send_json(200, {"software": result})
        except Exception as e:
            logging.exception("软件列表失败")
            self._send_json(200, {"software": [], "message": str(e)})

    def _handle_software_action(self, action, name):
        try:
            item = _find_software(self.config_file, name)
            if not item:
                self._send_json(404, {"success": False, "message": "未找到软件"})
                return
            lock = _get_sw_lock(name)
            with lock:
                if action == "start":
                    ok, msg = _start_software(item)
                elif action == "stop":
                    ok, msg = _stop_software(item)
                elif action == "restart":
                    ok, msg = _restart_software(item)
                else:
                    self._send_json(404, {"success": False, "message": "未知操作"})
                    return
            self._send_json(200, {"success": ok, "message": msg})
        except Exception as e:
            logging.exception("软件操作失败")
            self._send_json(500, {"success": False, "message": str(e)})

    def _handle_cmd_history(self):
        try:
            if self.command_runner is None:
                self._send_json(200, {"tasks": []})
                return
            self._send_json(200, {"tasks": self.command_runner.get_history()})
        except Exception as e:
            logging.exception("命令历史失败")
            self._send_json(500, {"success": False, "message": str(e)})

    def _handle_cmd_run(self):
        try:
            body = self._read_body()
            try:
                data = json.loads(body) if body else {}
            except Exception:
                data = {}
            cmd = (data.get("cmd") or "").strip()
            if not cmd:
                self._send_json(400, {"success": False, "message": "命令为空"})
                return
            if self.command_runner is None:
                self._send_json(500, {"success": False, "message": "命令执行器未初始化"})
                return
            task = self.command_runner.run(cmd)
            self._send_json(200, {
                "success": True,
                "task": task,
            })
        except Exception as e:
            logging.exception("命令执行失败")
            self._send_json(500, {"success": False, "message": str(e)})

    def _handle_cmd_stop(self):
        try:
            body = self._read_body()
            try:
                data = json.loads(body) if body else {}
            except Exception:
                data = {}
            task_id = (data.get("id") or "").strip()
            if not task_id:
                self._send_json(400, {"success": False, "message": "缺少任务ID"})
                return
            if self.command_runner is None:
                self._send_json(500, {"success": False, "message": "命令执行器未初始化"})
                return
            ok, msg = self.command_runner.stop(task_id)
            self._send_json(200, {"success": ok, "message": msg})
        except Exception as e:
            logging.exception("停止命令失败")
            self._send_json(500, {"success": False, "message": str(e)})
    # ---------- GET ----------
    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("/", "/index.html"):
                self._send_html(INDEX_HTML)
            elif path == "/api/status":
                self._send_json(200, self._dispatch_main_cmd("status"))
            elif path == "/api/software/list":
                self._handle_software_list()
            elif path == "/api/cmd/history":
                self._handle_cmd_history()
            else:
                self._send_json(404, {"success": False, "message": "Not Found"})
        except Exception as e:
            logging.exception("do_GET 异常")
            try:
                self._send_json(500, {"success": False, "message": str(e)})
            except Exception:
                pass

    # ---------- POST ----------
    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/api/unlock":
                self._send_json(200, self._dispatch_main_cmd("unlock"))
            elif path == "/api/lock":
                self._send_json(200, self._dispatch_main_cmd("lock"))
            elif path == "/api/shutdown":
                self._send_json(200, self._dispatch_main_cmd("shutdown"))
            elif path == "/api/reboot":
                self._send_json(200, self._dispatch_main_cmd("reboot"))
            elif path == "/api/toast":
                msg = query.get("msg", ["远程广播"])[0]
                self._send_json(200, self._dispatch_main_cmd("toast", {"msg": msg}))
            elif path == "/api/cmd/run":
                self._handle_cmd_run()
            elif path == "/api/cmd/stop":
                self._handle_cmd_stop()
            elif path.startswith("/api/software/"):
                action = path[len("/api/software/"):]
                name = query.get("name", [""])[0]
                self._handle_software_action(action, name)
            else:
                self._send_json(404, {"success": False, "message": "Not Found"})
        except Exception as e:
            logging.exception("do_POST 异常")
            try:
                self._send_json(500, {"success": False, "message": str(e)})
            except Exception:
                pass

    #----------远程命令------------
    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except Exception:
            return ""
        if length <= 0:
            return ""
        try:
            return self.rfile.read(length).decode("utf-8", errors="replace")
        except Exception:
            return ""

# ============================================================
# Server
# ============================================================

class WebControlServer:
    def __init__(self, main_queue, config_file, bind="0.0.0.0", port=8765):
        self.main_queue = main_queue
        self.config_file = config_file
        self.bind = bind
        self.port = port
        self.httpd = None
        self.thread = None
        self.command_runner = SyncCommandRunner(
            max_history=50,
            max_output=8192,
            default_timeout=30,
        )

    def start(self):
        try:
            _Handler.config_file = self.config_file
            _Handler.main_queue = self.main_queue
            _Handler.command_runner = self.command_runner
            self.httpd = ThreadingHTTPServer((self.bind, self.port), _Handler)
            self.httpd.daemon_threads = True
            self.thread = threading.Thread(
                target=self.httpd.serve_forever, daemon=True)
            self.thread.start()
            logging.info(f"Web 控制已启动: http://{self.bind}:{self.port}/")
            return True
        except Exception as e:
            logging.exception("启动 Web 控制失败")
            self.httpd = None
            self.thread = None
            return False

    def stop(self):
        try:
            if self.httpd:
                self.httpd.shutdown()
                self.httpd.server_close()
        except Exception:
            logging.exception("停止 Web 控制失败")
        finally:
            self.httpd = None
            self.thread = None