#!/usr/bin/env python3
"""Read-only MCP smoke and effective Docker boundary checks."""
import json, os, pathlib, selectors, subprocess, sys, time
root = pathlib.Path(__file__).resolve().parent
out = pathlib.Path("/srv/ai-data/tools/rea-lab-data/output")
log = (out / "mcp-stderr.log").open("wb")
p = subprocess.Popen([str(root / "rea-lab"), "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
sel = selectors.DefaultSelector(); sel.register(p.stdout, selectors.EVENT_READ)
buf = b""; seq = 0
def send(obj):
    p.stdin.write((json.dumps(obj)+"\n").encode()); p.stdin.flush()
def rpc(method, params, timeout=360):
    global seq, buf
    seq += 1; wanted = seq
    send({"jsonrpc":"2.0","id":wanted,"method":method,"params":params})
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        while b"\n" in buf:
            line,buf = buf.split(b"\n",1)
            if not line.strip(): continue
            msg=json.loads(line)
            if msg.get("id")==wanted:
                if "error" in msg: raise RuntimeError(msg["error"])
                return msg["result"]
        if not sel.select(max(0,end-time.monotonic())): break
        chunk=os.read(p.stdout.fileno(),65536)
        if not chunk: raise RuntimeError("MCP exited: "+str(p.poll()))
        buf+=chunk
    raise TimeoutError(method)
def save(name,obj):
    (out/name).write_text(json.dumps(obj,indent=2))
try:
    init=rpc("initialize",{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"ai-platform-rea-lab-smoke","version":"1.0"}})
    save("mcp-initialize.json",init)
    send({"jsonrpc":"2.0","method":"notifications/initialized"})
    listing=rpc("tools/list",{}); save("mcp-tools.json",listing)
    tools=listing["tools"]
    print("MCP_INITIALIZE=PASS", flush=True)
    print("MCP_TOOL_COUNT="+str(len(tools)), flush=True)
    ids=subprocess.check_output(["docker","ps","-q","--filter","label=ai-platform.lab=rea"],text=True).split()
    assert len(ids)==1,ids
    cid=ids[0]
    info=json.loads(subprocess.check_output(["docker","inspect",cid],text=True))[0]
    h=info["HostConfig"]
    assert h["NetworkMode"]=="none" and h["ReadonlyRootfs"]
    assert h["Memory"]==4*1024**3 and h["MemorySwap"]==4*1024**3
    assert h["NanoCpus"]==2000000000 and h["PidsLimit"]==256
    assert "ALL" in h["CapDrop"] and "no-new-privileges:true" in h["SecurityOpt"]
    assert info["Config"]["User"]=="1000:1000"
    assert not h.get("Privileged") and not h.get("Devices") and not h.get("DeviceRequests")
    assert not h.get("PortBindings") and h.get("PidMode")!="host"
    expected={"/input","/work","/home/node"}
    assert {m["Destination"] for m in info["Mounts"] if m["Type"]=="bind"}==expected
    assert next(m for m in info["Mounts"] if m["Destination"]=="/input")["RW"] is False
    inner='import os,pathlib,socket; assert os.getuid()==1000; assert not any(pathlib.Path(p).exists() for p in ["/dev/dri","/dev/kfd","/var/run/docker.sock","/home/harrypotter","/srv/ai-data"]); s=socket.socket(); s.settimeout(1); assert s.connect_ex(("127.0.0.1",11434))!=0; status=pathlib.Path("/proc/self/status").read_text(); assert "CapEff:\\t0000000000000000" in status; assert "NoNewPrivs:\\t1" in status; assert "Seccomp:\\t2" in status; print("INSIDE_BOUNDARY=PASS")'
    print(subprocess.check_output(["docker","exec",cid,"python3","-c",inner],text=True).strip(),flush=True)
    save("isolation.json",{"result":"PASS","container_id":cid,"host_config":h,"mounts":info["Mounts"],"user":info["Config"]["User"]})
    print("ISOLATION=PASS",flush=True)
    if "--discover" in sys.argv:
        for t in tools:
            if t["name"] in ("open_binary","close_binary","list_functions","decompile_function","binary_session") or "decompile" in t["name"]:
                print(json.dumps({"name":t["name"],"inputSchema":t["inputSchema"]}),flush=True)
    else:
        def call(name,args,filename):
            result=rpc("tools/call",{"name":name,"arguments":args})
            save(filename,result)
            if result.get("isError"): raise RuntimeError(name+": "+json.dumps(result)[:5000])
            print(name+"=PASS",flush=True)
            return result
        call("binary_session",{},"session-before.json")
        call("open_binary",{"path":"/input/ecu_demo","provider_id":"ghidra"},"open.json")
        funcs=call("list_procedures",{},"functions.json")
        assert "pressure_to_dtc" in json.dumps(funcs)
        pseudo=call("procedure_pseudo_code",{"procedure":"pressure_to_dtc"},"decompile.json")
        text=pseudo["structuredContent"]["normalized_result"].lower()
        assert "0x1234" in text or "4660" in text
        assert "0x5678" in text or "22136" in text
        assert "pressure < 0xfb" in text or "pressure > 250" in text
        call("procedure_assembly",{"procedure":"pressure_to_dtc"},"assembly.json")
        call("procedure_callers",{"procedure":"pressure_to_dtc"},"callers.json")
        call("binary_session",{},"session-open.json")
        # Verify heap limits at the actual Ghidra JVM after provider startup.
        measure="import pathlib,json\nrows=[]\nfor proc in pathlib.Path(\"/proc\").glob(\"[0-9]*\"):\n    try:\n        cmd=(proc/\"cmdline\").read_bytes().split(b\"\\0\")\n        exe=pathlib.Path(cmd[0].decode()).name if cmd and cmd[0] else \"\"\n        if exe==\"java\" and b\"-Xmx2G\" in cmd:\n            rows.append({\"pid\":proc.name,\"heap\":\"2G\",\"status\":[line for line in (proc/\"status\").read_text().splitlines() if line.startswith((\"VmRSS:\",\"Cpus_allowed_list:\"))]})\n    except (OSError,ValueError):\n        pass\nassert rows, \"Ghidra JVM not observed\"\nprint(json.dumps(rows))\n"
        measured=json.loads(subprocess.check_output(["docker","exec",cid,"python3","-c",measure],text=True))
        save("jvm-measurement.json",measured)
        call("close_binary",{},"close.json")
        session=call("binary_session",{},"session-closed.json")
        # REA text content may include its explicit untrusted-data marker.
        structured=session.get("structuredContent")
        if structured is not None:
            assert structured["result"]["open"] is False
            assert structured["result"]["cleanup_pending"] is False
        save("smoke-result.json",{"result":"PASS","mcp_tools":len(tools),"isolation":"PASS","target":"synthetic x86_64 ELF with symbols","decompiled_conditions":["sensor_ok","pressure > 250","0x1234","0x5678"],"jvm":measured})
        print("REA_MCP_NATIVE_SMOKE=PASS",flush=True)

finally:
    p.stdin.close()
    try: p.wait(timeout=20)
    except subprocess.TimeoutExpired: p.terminate(); p.wait(timeout=10)
    log.close()
