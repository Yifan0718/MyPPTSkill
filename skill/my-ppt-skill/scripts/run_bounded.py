"""Bound a task-owned invocation and retain its result as optional render evidence."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,math,os,subprocess,sys,uuid,signal
from report_io import emit_report

def stop_owned_tree(child):
    if child is None or child.poll() is not None:return
    if os.name=='nt':
        # taskkill /T is restricted to this still-running task-owned PID.
        result=subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode and child.poll() is None:child.kill()
    else:os.killpg(child.pid,signal.SIGKILL)
    child.wait(timeout=10)


def run(command,timeout,status_report=None):
    if not command or not math.isfinite(timeout) or timeout<=0:
        print(json.dumps({'status':'failed','reason':'Provide a command and a positive finite timeout.'}),file=sys.stderr);return 3
    status_report=Path(status_report) if status_report is not None else None
    inputs=[]
    for x in command:
        try:
            if isinstance(x,str) and Path(x).is_file():inputs.append(Path(x))
        except (OSError,ValueError):pass
    record={'schema':'bounded-run/v1','run_id':uuid.uuid4().hex,'status':'running','timeout_seconds':timeout,'started_at':datetime.now(timezone.utc).isoformat()}
    if status_report:
        if status_report.exists():
            print(json.dumps({'status':'failed','reason':'Use a fresh status-report path; previous run evidence is retained.'}),file=sys.stderr);return 3
        if emit_report(status_report,record,inputs=inputs):return 3
    def finish(code,status):
        record.update(status=status,exit_code=code,finished_at=datetime.now(timezone.utc).isoformat())
        if status_report and emit_report(status_report,record,inputs=inputs):return 3
        return code
    child=None
    try:
        child=subprocess.Popen(command,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0,start_new_session=os.name!='nt')
        return finish(child.wait(timeout=timeout),'finished')
    except subprocess.TimeoutExpired:
        if child:
            try:stop_owned_tree(child)
            except (OSError,subprocess.TimeoutExpired):pass
        print(json.dumps({'status':'failed','reason':'task_tool_timeout','timeout_seconds':timeout,
                          'recovery':'Keep the incomplete run as failed. Inspect tool availability and task-owned resources; retry in a fresh output directory with an appropriate timeout or use another renderer. Do not terminate unrelated Office sessions.'}),file=sys.stderr)
        return finish(3,'timed_out')
    except KeyboardInterrupt:
        if child:
            try:stop_owned_tree(child)
            except (OSError,subprocess.TimeoutExpired):pass
        print(json.dumps({'status':'failed','reason':'task_cancelled','recovery':'Keep this run incomplete; resume only when the user requests continuation.'}),file=sys.stderr)
        return finish(130,'cancelled')
    except (OSError,ValueError) as e:
        print(json.dumps({'status':'failed','reason':str(e),'recovery':'Check the executable path and environment, then retry the same task.'}),file=sys.stderr);return finish(3,'failed')

def main():
    p=argparse.ArgumentParser();p.add_argument('--timeout',type=float,default=300);p.add_argument('--status-report',type=Path);p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
    command=a.command[1:] if a.command and a.command[0]=='--' else a.command
    return run(command,a.timeout,a.status_report)
if __name__=='__main__':raise SystemExit(main())
