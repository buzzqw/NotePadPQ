"""usage: bench.py SCENARIO [args]; prints a JSON line prefixed BENCH=."""
from pathlib import Path
import os, sys, time, json, statistics, cProfile, pstats, io
T0=time.perf_counter()
REPO=os.environ.get("REPO", str(Path(__file__).resolve().parents[2])); sys.path.insert(0,REPO); os.chdir(REPO)
if os.environ.get("SWITCH"): sys.setswitchinterval(float(os.environ["SWITCH"]))
from pathlib import Path
import psutil
P=psutil.Process()
rss=lambda: round(P.memory_info().rss/1048576,1)
uss=lambda: round(P.memory_full_info().uss/1048576,1)
cpu=lambda: sum(P.cpu_times()[:2])
R={"scenario":sys.argv[1:]}
stage={}
def mark(n): stage[n]={"t":round(time.perf_counter()-T0,3),"rss":rss(),"mods":len(sys.modules)}
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer, QEventLoop
from PyQt6.QtTest import QTest
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
app=QApplication(["bench"]); app.setApplicationName("NotePadPQ"); app.setOrganizationName("NotePadPQ")
mark("qapp")
from config.settings import Settings
from ui.main_window import MainWindow
mark("import_main_window")
if os.environ.get("NOWRAP"): Settings.instance().set("editor/word_wrap",False)
win=MainWindow(); mark("MainWindow()")
win.show(); app.processEvents(); mark("show")
def spin(sec):
    l=QEventLoop(); QTimer.singleShot(int(sec*1000),l.quit); l.exec()
def startup():
    from plugins.plugin_manager import PluginManager
    pm=PluginManager.instance(); done=[]
    pl=[]; orig=pm._load_plugin_file
    def tl(path,w):
        t=time.perf_counter(); m=rss(); r=orig(path,w); pl.append((path.stem,round((time.perf_counter()-t)*1000,1),round(rss()-m,1))); return r
    pm._load_plugin_file=tl
    pm.load_all_deferred(win,on_done=lambda:done.append(1))
    while not done: app.processEvents(); time.sleep(0.0005)
    mark("plugins")
    win._rebuild_toolbar()
    from ui.smart_highlight import MultiMarkManager, SmartHighlighter
    win._smart_highlighter=SmartHighlighter.install_into_main_window(win)
    win._mark_manager=MultiMarkManager.install_into_main_window(win)
    from ui.incremental_search import IncrementalSearchBar
    win._inc_search=IncrementalSearchBar.install(win)
    for m in ("function_list","include_list","json_xml_panel","git_blame_inline"):
        __import__("ui."+m,fromlist=["install"]).install(win)
    mark("finish_startup")
    from core.session import Session
    Session.instance().restore_ui_state(win)
    spin(1.0); mark("settled")
    R["plugins"]=sorted(pl,key=lambda x:-x[1])[:12]
startup()
kind=sys.argv[1]
class Lag:
    def __init__(s): s.v=[];s.last=None;s.t=QTimer();s.t.setInterval(10);s.t.timeout.connect(s.tick)
    def start(s): s.last=time.perf_counter();s.t.start()
    def tick(s):
        n=time.perf_counter();s.v.append((n-s.last)*1000-10);s.last=n
    def stop(s):
        s.t.stop();v=sorted(s.v) or [0]
        return {"p50":round(v[len(v)//2],1),"p95":round(v[int(len(v)*.95)],1),"max":round(v[-1],1),"over50ms":sum(x>50 for x in v)}
def wait_loaded(ed,limit=600):
    end=time.perf_counter()+limit
    while time.perf_counter()<end:
        app.processEvents(); time.sleep(0.001)
        if ed.length()>0 and win._tab_manager.current_editor() is ed:
            l=getattr(ed,'_lazy_loader',None)
            if not getattr(ed,'_editor_load_active',False):
                return
if kind=="startup":
    R["stage"]=stage; R["uss"]=uss(); R["threads"]=P.num_threads()
    R["top_prefix_mods"]=len(sys.modules)
    heavy=[m for m in ("PyQt6.QtWebEngineWidgets","PyQt6.QtNetwork","PyQt6.QtPrintSupport","PyQt6.QtSql","pygments","markdown","docutils","chardet","numpy","matplotlib","fitz","requests","paramiko","cryptography","openpyxl","keyring","spellchecker","sympy","psutil","asyncio","ssl","email","http.client","urllib.request","xml.dom.minidom","sqlite3","concurrent.futures") if m in sys.modules]
    R["heavy_loaded"]=heavy
elif kind=="open":
    f=Path(sys.argv[2]); m0=rss(); c0=cpu(); t=time.perf_counter()
    win.open_files([f]); t1=time.perf_counter()
    ed=win._tab_manager.current_editor()
    # wait until document fully loaded
    size=f.stat().st_size
    while ed.length()<size*0.98 and time.perf_counter()-t<600:
        app.processEvents(); time.sleep(0.001)
    t2=time.perf_counter()
    lag=Lag(); lag.start(); spin(6.0)
    R.update(open_call_s=round(t1-t,3),loaded_s=round(t2-t,3),rss_before=m0,rss_after=rss(),rss_delta=round(rss()-m0,1),cpu_s=round(cpu()-c0,2),lag_after=lag.stop(),lexer=type(ed.lexer()).__name__,lines=ed.lines(),hl=len(getattr(ed,'_smart_hl_word','') or ''))
elif kind=="type":
    f=Path(sys.argv[2]); prof=len(sys.argv)>3 and sys.argv[3]=="prof"
    win.open_files([f]); ed=win._tab_manager.current_editor(); size=f.stat().st_size
    while ed.length()<size*0.98: app.processEvents(); time.sleep(0.001)
    spin(3.0)
    ed.setFocus(); ed.setCursorPosition(ed.lines()//2,0); spin(0.5)
    txt="value = result + index "*13
    lat=[]; c0=cpu(); t00=time.perf_counter(); lag=Lag(); lag.start()
    pr=cProfile.Profile() if prof else None
    if pr: pr.enable()
    for ch in txt:
        t=time.perf_counter(); QTest.keyClick(ed,ch); app.processEvents(); lat.append((time.perf_counter()-t)*1000)
        # 12 chars/s realistic human: remaining wait in event loop
        rest=0.08-(time.perf_counter()-t)
        if rest>0: spin(rest)
    spin(4.0) # let debounced work fire
    if pr:
        pr.disable(); s=io.StringIO(); pstats.Stats(pr,stream=s).sort_stats("cumulative").print_stats(45); R["prof"]=s.getvalue()
        s=io.StringIO(); pstats.Stats(pr,stream=s).sort_stats("tottime").print_stats(25); R["prof_tot"]=s.getvalue()
    lat.sort(); wall=time.perf_counter()-t00; cs=cpu()-c0
    R.update(keys=len(lat),key_ms={"p50":round(lat[len(lat)//2],1),"p95":round(lat[int(len(lat)*.95)],1),"max":round(lat[-1],1)},lag=lag.stop(),cpu_pct=round(cs/wall*100,1),cpu_s=round(cs,2),wall=round(wall,1),rss=rss(),lexer=type(ed.lexer()).__name__)
elif kind=="tabs":
    d=Path(sys.argv[2]); fs=sorted(d.glob("tab*.py")); m0=rss(); u0=uss(); t=time.perf_counter()
    per=[]
    for f in fs:
        t1=time.perf_counter(); win.open_files([f]); app.processEvents(); per.append(round((time.perf_counter()-t1)*1000,1))
    t2=time.perf_counter(); spin(3.0)
    R.update(n=len(fs),open_all_s=round(t2-t,3),per_tab_ms={"first":per[0],"median":statistics.median(per),"max":max(per),"last":per[-1]},rss_delta=round(rss()-m0,1),uss_delta=round(uss()-u0,1),per_tab_mb=round((uss()-u0)/len(fs),2),threads=P.num_threads())
    # tab switching
    sw=[]
    tm=win._tab_manager
    for i in range(len(tm.all_editors())):
        t1=time.perf_counter(); tm.set_current_index(i); app.processEvents(); sw.append((time.perf_counter()-t1)*1000)
    sw.sort(); R["switch_ms"]={"p50":round(sw[len(sw)//2],1),"max":round(sw[-1],1)}
    spin(5); c0=cpu(); spin(20); R["idle_cpu_pct_30tabs"]=round((cpu()-c0)/20*100,2)
    from PyQt6.QtCore import QObject
    R["qtimers_active"]=sum(1 for t in win.findChildren(QTimer) if t.isActive()); R["qtimers"]=len(win.findChildren(QTimer))
    R["editor_children"]=len(tm.current_editor().findChildren(QObject))
elif kind=="openprof":
    f=Path(sys.argv[2]); before=set(sys.modules); m0=rss()
    pr=cProfile.Profile(); pr.enable(); win.open_files([f]); ed=win._tab_manager.current_editor(); spin(float(sys.argv[3]) if len(sys.argv)>3 else 8.0); pr.disable()
    new=sorted(set(sys.modules)-before); R["new_mods_n"]=len(new)
    R["new_top"]=sorted({m.split('.')[0] for m in new}); R["rss_delta"]=round(rss()-m0,1)
    R["webengine"]="PyQt6.QtWebEngineWidgets" in sys.modules
    s=io.StringIO(); pstats.Stats(pr,stream=s).sort_stats("cumulative").print_stats(60); R["prof"]=s.getvalue()
    s=io.StringIO(); pstats.Stats(pr,stream=s).sort_stats("tottime").print_stats(25); R["prof_tot"]=s.getvalue()
elif kind=="real":
    import threading, collections, ctypes, gc
    class Sampler:
        def __init__(s): s.c=collections.Counter(); s.n=0; s.on=False; s.me=None; s.perthread=collections.Counter()
        def run(s):
            s.me=threading.get_ident(); main=threading.main_thread().ident
            while s.on:
                time.sleep(0.005); s.n+=1
                for tid,fr in sys._current_frames().items():
                    if tid==s.me: continue
                    who="GUI" if tid==main else "WK"
                    f=fr; stack=[]
                    while f and len(stack)<40:
                        stack.append(f); f=f.f_back
                    leaf=stack[0]
                    if who=="GUI" and leaf.f_code.co_name in("spin",): continue
                    if who=="WK" and leaf.f_code.co_name in ("wait","_wait_for_tstate_lock","_worker","get"): continue
                    repo=next((x for x in stack if "/NotePadPQ/" in x.f_code.co_filename and ".venv" not in x.f_code.co_filename and "bench" not in x.f_code.co_filename),None)
                    if repo is None: continue
                    # top-most repo entry (what started the work) + leaf repo
                    rs=[x for x in stack if "/NotePadPQ/" in x.f_code.co_filename and ".venv" not in x.f_code.co_filename]
                    top=rs[-1]; n=lambda x:x.f_code.co_filename.split("/NotePadPQ/")[1]+":"+x.f_code.co_name
                    s.c[(who,n(repo))]+=1; s.perthread[who+" entry "+n(top)]+=1
        def start(s): s.c.clear(); s.perthread.clear(); s.n=0; s.on=True; threading.Thread(target=s.run,daemon=True).start()
        def stop(s):
            s.on=False; time.sleep(0.02)
            ms=lambda k:round(k*5.5)
            return {"leaf":[(k[0],k[1],ms(v)) for k,v in s.c.most_common(22)],"entry":[(k,ms(v)) for k,v in s.perthread.most_common(14)]}
    def quiesce(limit=60):
        """time until process CPU drops under 5% over a 500ms window"""
        t=time.perf_counter(); 
        while time.perf_counter()-t<limit:
            c=cpu(); spin(0.5)
            if (cpu()-c)/0.5<0.05: break
        return round(time.perf_counter()-t,2)
    f=Path(sys.argv[2]); m0=rss(); c0=cpu(); S=Sampler(); S.start(); L=Lag(); L.start(); t=time.perf_counter()
    win.open_files([f]); call=time.perf_counter()-t; ed=win._tab_manager.current_editor(); size=f.stat().st_size
    while ed.length()<size*0.9 and time.perf_counter()-t<300: app.processEvents(); time.sleep(0.001)
    loaded=time.perf_counter()-t
    q=quiesce(90); peak=rss()
    R.update(file=f.name,size_mb=round(size/1048576,2),lexer=type(ed.lexer()).__name__,lines=ed.lines(),open_call_s=round(call,3),loaded_s=round(loaded,3),settle_s=round(q+loaded,2),open_cpu_s=round(cpu()-c0,2),rss_delta=round(rss()-m0,1),open_lag=L.stop(),open_samples=S.stop())
    gc.collect(); r1=rss()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception: pass
    R["rss_after_gc"]=round(r1-m0,1); R["rss_after_trim"]=round(rss()-m0,1)
    # scroll
    ed.setFocus(); spin(0.3)
    sc=[]; n=ed.lines()
    for i in range(40):
        t=time.perf_counter(); ed.setFirstVisibleLine(int(n*i/40)); app.processEvents(); sc.append((time.perf_counter()-t)*1000); spin(0.02)
    sc.sort(); R["jump_scroll_ms"]={"p50":round(sc[20],1),"max":round(sc[-1],1)}
    ed.setCursorPosition(n//2,0); spin(1.0)
    ar=[]; c1=cpu(); t1=time.perf_counter()
    for i in range(120):
        t=time.perf_counter(); QTest.keyClick(ed,Qt.Key.Key_Down); app.processEvents(); ar.append((time.perf_counter()-t)*1000); spin(0.03)
    spin(1.5)
    ar.sort(); R["arrow_ms"]={"p50":round(ar[60],1),"p95":round(ar[114],1),"max":round(ar[-1],1)}; R["arrow_cpu_pct"]=round((cpu()-c1)/(time.perf_counter()-t1)*100,1)
    q2=quiesce(30)
    # typing
    ed.setCursorPosition(n//2,0); spin(0.5)
    txt="value and result of index "*7; lat=[]; c1=cpu(); t1=time.perf_counter(); m1=rss(); S=Sampler(); S.start(); L=Lag(); L.start()
    for ch in txt:
        t=time.perf_counter(); QTest.keyClick(ed,ch); app.processEvents(); d=time.perf_counter()-t; lat.append(d*1000); spin(max(0.001,0.09-d))
    tw=time.perf_counter()-t1; cw=cpu()-c1; rtype=rss()
    settle=quiesce(40)
    lat.sort(); R.update(keys=len(lat),key_ms={"p50":round(lat[len(lat)//2],1),"p95":round(lat[int(len(lat)*.95)],1),"max":round(lat[-1],1)},type_cpu_pct=round(cw/tw*100,1),type_settle_s=settle,type_cpu_total_s=round(cpu()-c1,2),type_rss_delta=round(rss()-m1,1),type_lag=L.stop(),type_samples=S.stop(),rss_final=rss())
elif kind=="pause":
    # realistic: 12 chars then 4s pause, N rounds, on a real doc
    f=Path(sys.argv[2]); win.open_files([f]); ed=win._tab_manager.current_editor(); size=f.stat().st_size
    while ed.length()<size*0.9: app.processEvents(); time.sleep(0.001)
    spin(8); ed.setFocus(); n=ed.lines(); ed.setCursorPosition(n//2,0); spin(1)
    m1=rss(); c1=cpu(); t1=time.perf_counter(); L=Lag(); L.start(); series=[]; lat=[]
    for r in range(8):
        for ch in "index value ":
            t=time.perf_counter(); QTest.keyClick(ed,ch); app.processEvents(); d=time.perf_counter()-t; lat.append(d*1000); spin(max(0.001,0.09-d))
        spin(4.0); series.append(rss())
    lat.sort()
    wall=time.perf_counter()-t1
    R.update(file=f.name,wrap=str(ed.wrapMode()),lexer=type(ed.lexer()).__name__,cpu_s=round(cpu()-c1,2),wall=round(wall,1),cpu_pct=round((cpu()-c1)/wall*100,1),lag=L.stop(),key_ms={"p50":round(lat[len(lat)//2],1),"p95":round(lat[int(len(lat)*.95)],1),"max":round(lat[-1],1)},rss_series=series,rss_growth=round(rss()-m1,1))
elif kind=="roots":
    import core.latex_project as lp, core.latex_index as li, traceback
    orig=lp.resolve_project_root; log=[]
    def w(cur,content=None):
        r=orig(cur,content); log.append((Path(cur).name,None if content is None else len(content),Path(r).name,[x.name.split('.')[0] for x in [] ])); return r
    lp.resolve_project_root=w; li.resolve_project_root=w
    os_=lp._scan_root; sc=[]
    def ws(d):
        r=os_(d); sc.append((str(d)[-30:],r.name if r else None)); return r
    lp._scan_root=ws
    f=Path(sys.argv[2]); m0=rss(); win.open_files([f]); spin(10)
    cache=li._DEFAULT_ANALYSIS_CACHE if hasattr(li,"_DEFAULT_ANALYSIS_CACHE") else None
    R.update(file=f.name,calls=log[:20],ncalls=len(log),scan=sc,rss_delta=round(rss()-m0,1))
    src=lp._DEFAULT_SOURCE_CACHE
    R["source_cache_files"]=[(p.name,len(v[1])) for p,v in src._files.items()]
    R["stripped_files"]=[(p.name,len(v[1])) for p,v in src._stripped.items()]
elif kind=="mem":
    import tracemalloc,gc
    tracemalloc.start(1)
    f=Path(sys.argv[2]); s0=tracemalloc.take_snapshot(); m0=rss(); win.open_files([f]); ed=win._tab_manager.current_editor(); spin(12); gc.collect()
    s1=tracemalloc.take_snapshot(); cur,peak=tracemalloc.get_traced_memory()
    d=s1.compare_to(s0,"lineno")
    R.update(file=f.name,rss_delta=round(rss()-m0,1),py_traced_mb=round(cur/1048576,1),py_peak_mb=round(peak/1048576,1),top=[(str(x.traceback[0]).replace(REPO+"/",""),round(x.size_diff/1048576,2),x.count_diff) for x in d[:22]])
elif kind=="brk":
    f=Path(sys.argv[2]); where=sys.argv[3]; proto=sys.argv[4] if len(sys.argv)>4 else ""
    from editor.autocomplete import AutoCompleteManager as AC
    from editor.lexer_latex_custom import LaTeXLexer as LX
    import functools
    acc={}
    def wrap(cls,name):
        o=getattr(cls,name)
        def w(*a,**k):
            t=time.perf_counter()
            try: return o(*a,**k)
            finally:
                e=acc.setdefault(name,[0,0.0]); e[0]+=1; e[1]+=time.perf_counter()-t
        setattr(cls,name,w)
    wrap(AC,"_show_custom_completion"); wrap(LX,"styleText")
    if proto=="labelcache":
        AC._completion_label=staticmethod(functools.lru_cache(maxsize=None)(AC._completion_label))
    win.open_files([f]); ed=win._tab_manager.current_editor(); size=f.stat().st_size
    while ed.length()<size*0.9: app.processEvents(); time.sleep(0.001)
    spin(5); ed.setFocus(); n=ed.lines(); ed.setCursorPosition({"mid":n//2,"end":n-3,"top":5}[where],0); spin(.5)
    pos=ed.SendScintilla(ed.SCI_GETCURRENTPOS)
    t=time.perf_counter()
    for _ in range(5): ed.SendScintilla(ed.SCI_COUNTCHARACTERS,0,pos)
    R["countchars_ms"]=round((time.perf_counter()-t)/5*1000,2)
    n0=ed.SendScintilla(ed.SCI_GETLENGTH); buf=bytearray(n0+1); t=time.perf_counter()
    for _ in range(5):
        ed.SendScintilla(ed.SCI_GETTEXT,n0+1,buf); b=bytes(buf[:n0])
    R["gettext_copy_ms"]=round((time.perf_counter()-t)/5*1000,2)
    acc.clear(); lat=[]
    for ch in "index value and result "*8:
        t=time.perf_counter(); QTest.keyClick(ed,ch); app.processEvents(); d=time.perf_counter()-t; lat.append(d*1000); spin(max(0.001,0.05-d))
    lat.sort(); k=len(lat)
    ac=ed._autocomplete
    R.update(file=f.name,where=where,proto=proto,pos=pos,key_p50=round(lat[k//2],1),key_p95=round(lat[int(k*.95)],1),per_key={m:round(v[1]/k*1000,2) for m,v in acc.items()},calls={m:v[0] for m,v in acc.items()},n_doc_words=len(ac._document_words_cache),n_local=len(ac._local_completion_terms))
elif kind=="pdf":
    from ui.preview_panel import PreviewPanel
    import fitz
    tex=Path(sys.argv[2]); pdf=tex.with_suffix(".pdf")
    win.open_files([tex]); ed=win._tab_manager.current_editor(); spin(4)
    m0=rss(); c0=cpu(); P_=PreviewPanel(); P_.resize(800,1000); P_.show(); spin(.3)
    R["rss_panel"]=round(rss()-m0,1)
    P_._editor=ed; P_._mode="pdf"; L=Lag(); L.start()
    t=time.perf_counter(); P_._render_pdf(); R["render_pdf_ms"]=round((time.perf_counter()-t)*1000); spin(2)
    R["single_page_rss"]=round(rss()-m0,1); R["lag_load"]=L.stop(); R["pages"]=len(P_._pdf_doc) if P_._pdf_doc is not None else None
    # raw costs
    t=time.perf_counter(); d=fitz.open(str(pdf)); R["fitz_open_ms"]=round((time.perf_counter()-t)*1000,1)
    t=time.perf_counter(); pg=d[100]; px=pg.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False); R["raster_p100_ms"]=round((time.perf_counter()-t)*1000,1); R["pix_mb"]=round(len(px.samples)/1048576,2); d.close()
    # continuous
    m1=rss(); L=Lag(); L.start(); t=time.perf_counter(); P_._pdf_toggle_continuous(True); R["toggle_cont_ms"]=round((time.perf_counter()-t)*1000); spin(2.5)
    R["cont_rss_delta"]=round(rss()-m1,1); R["cont_widgets"]=len(P_._pdf_cont_container.findChildren(__import__("PyQt6.QtWidgets",fromlist=["QWidget"]).QWidget)); R["lag_cont"]=L.stop()
    sb=P_._pdf_scroll_cont.verticalScrollBar(); L=Lag(); L.start(); peak=rss(); c1=cpu(); t1=time.perf_counter()
    for i in range(60):
        sb.setValue(int(sb.maximum()*i/60)); spin(0.15); peak=max(peak,rss())
    spin(2); gc=__import__("gc"); gc.collect()
    R["scroll"]={"cpu_pct":round((cpu()-c1)/(time.perf_counter()-t1)*100),"lag":L.stop(),"rss_peak_delta_from_m0":round(peak-m0,1),"rss_after":round(rss()-m0,1),"rendered_now":len(P_._pdf_cont_rendered)}
    # rebuild as after compile
    t=time.perf_counter(); P_._pdf_cont_relayout(); R["relayout_ms"]=round((time.perf_counter()-t)*1000); spin(2)
    t=time.perf_counter(); P_._pdf_zoom_in_action(); R["zoom_ms"]=round((time.perf_counter()-t)*1000); spin(2)
    R["rss_total_final"]=rss()
elif kind=="verify":
    f=Path(sys.argv[2]); win.open_files([f]); ed=win._tab_manager.current_editor(); size=f.stat().st_size
    while ed.length()<size*0.9: app.processEvents(); time.sleep(0.001)
    spin(4); ed.setFocus(); n=ed.lines()
    def styles(a,b): return [ed.SendScintilla(ed.SCI_GETSTYLEAT,p) for p in range(a,b)]
    bad=0; rounds=0
    for frac in (0.1,0.5,0.9):
        line=int(n*frac); ed.setCursorPosition(line,0); ed.setFirstVisibleLine(line); spin(.2)
        for ch in "\\textbf{ciao} $x+y$ % nota":
            QTest.keyClick(ed,ch); app.processEvents()
        QTest.keyClick(ed,Qt.Key.Key_Escape); QTest.keyClick(ed,Qt.Key.Key_Return); QTest.keyClick(ed,Qt.Key.Key_Backspace); spin(.3)
        a=ed.SendScintilla(ed.SCI_POSITIONFROMLINE,line); b=min(ed.length(),a+3000)
        before=styles(a,b)
        lx=ed.lexer(); lx.recolor(); ed.setFirstVisibleLine(line); spin(.3)
        after=styles(a,b); rounds+=1; bad+=sum(x!=y for x,y in zip(before,after))
    R["style_diff_bytes"]=bad; R["rounds"]=rounds
    # undo restores content exactly
    txt=ed.text(); 
    for _ in range(60): ed.undo()
    R["undo_restored_disk"]= ed.text()==f.read_text(encoding="utf-8",errors="replace").replace("\r\n","\n"); R["modified_after_undo"]=ed.isModified()
    # PDF drawing
    from ui.preview_panel import PreviewPanel
    from PyQt6.QtGui import QImage
    pp=PreviewPanel(); pp.resize(800,1000); pp.show(); spin(.3); pp._editor=ed; pp._mode="pdf"; pp._render_pdf(); spin(.5); pp._pdf_toggle_continuous(True); spin(1.5)
    sb=pp._pdf_scroll_cont.verticalScrollBar(); R["sb_max"]=sb.maximum(); pp._scroll_cont_to_page(100); spin(2.0)
    R["page_label"]=pp._pdf_lbl_page.text().strip(); R["sb_val"]=sb.value(); R["page100_y"]=pp._pdf_cont_page_labels[100].y(); R["rendered"]=sorted(pp._pdf_cont_rendered)
    img=pp._pdf_scroll_cont.viewport().grab().toImage(); dark=0;tot=0
    for y in range(0,img.height(),7):
        for x in range(0,img.width(),7):
            c=img.pixelColor(x,y); tot+=1; dark+= c.lightness()<140
    R["vp_dark_ratio"]=round(dark/tot,3); img.save(os.environ["SHOT"]) 
    m=rss(); spin(7.0); R["rss_before_idle"]=m; R["rss_after_idle_release"]=rss()
    pp._pdf_cont_clicked(100,50,50); spin(.2); R["click_ok"]=True
elif kind=="overlap":
    if os.environ.get("SWITCH"): sys.setswitchinterval(float(os.environ["SWITCH"]))
    f=Path(sys.argv[2]); preview=len(sys.argv)>3 and sys.argv[3]=="preview"
    win.open_files([f]); ed=win._tab_manager.current_editor(); size=f.stat().st_size
    while ed.length()<size*0.9: app.processEvents(); time.sleep(0.001)
    spin(6)
    pp=None
    if preview:
        from ui.preview_panel import PreviewPanel
        pp=PreviewPanel(); pp.resize(800,1000); pp.show(); spin(.2); pp.set_editor(ed); spin(1.0)
        pp._mode="pdf"; pp._editor=ed; pp._render_pdf(); spin(.5); pp._pdf_toggle_continuous(True); spin(2)
    ed.setFocus(); n=ed.lines(); ed.setCursorPosition(n//2,0); spin(.5)
    lat=[]; L=Lag(); L.start(); c1=cpu(); t1=time.perf_counter(); first=[]
    # pause lengths around the debounce windows (checker 1.5s, words 1.2s, index 3s)
    for pause in (3.2,3.4,3.6,1.7,3.3,2.0,3.5,3.2):
        for i,ch in enumerate("alpha beta gamma "):
            t=time.perf_counter(); QTest.keyClick(ed,ch); app.processEvents(); d=(time.perf_counter()-t)*1000; lat.append(d)
            spin(max(0.001,0.09-d/1000))
        spin(pause)
    lat.sort(); k=len(lat)
    R.update(file=f.name,preview=preview,switch=sys.getswitchinterval(),mode=getattr(pp,"_mode",None),key={"p50":round(lat[k//2],1),"p95":round(lat[int(k*.95)],1),"p99":round(lat[int(k*.99)],1),"max":round(lat[-1],1)},over50=sum(x>50 for x in lat),over100=sum(x>100 for x in lat),n=k,lag=L.stop(),cpu_pct=round((cpu()-c1)/(time.perf_counter()-t1)*100,1))
elif kind=="spikes":
    import functools
    acc={}
    def wrap(cls,name,label=None):
        o=getattr(cls,name); lab=label or cls.__name__+"."+name
        @functools.wraps(o)
        def w(*a,**k):
            t=time.perf_counter()
            try: return o(*a,**k)
            finally:
                d=(time.perf_counter()-t)*1000; e=acc.setdefault(lab,[0,0.0,0.0]); e[0]+=1;e[1]+=d;e[2]=max(e[2],d)
        setattr(cls,name,w)
    from editor.latex_checker import LaTeXChecker as C
    from editor.autocomplete import AutoCompleteManager as AC
    from editor.editor_widget import EditorWidget as E
    from ui.tab_manager import TabManager as TM
    from ui.language_toolbar import LanguageToolbar as LT
    from ui.main_window import MainWindow as MW
    for c,n in ((C,"_on_check_done"),(C,"_apply_markers"),(C,"_apply_tabular_indicators"),(C,"_run_check"),(AC,"_rebuild_api"),(AC,"_on_latex_document_words"),(AC,"_on_api_ready"),(E,"load_content"),(E,"text"),(TM,"new_tab"),(LT,"_rebuild"),(MW,"_on_editor_changed"),(MW,"_after_open"),(E,"_do_smart_highlight")):
        try: wrap(c,n)
        except AttributeError: pass
    lags=[]; 
    f=Path(sys.argv[2]); L=Lag(); L.start(); t=time.perf_counter(); win.open_files([f]); R["open_call_ms"]=round((time.perf_counter()-t)*1000); ed=win._tab_manager.current_editor(); spin(6)
    R["open_lag"]=L.stop(); R["open_fn"]={k:[v[0],round(v[1]),round(v[2])] for k,v in sorted(acc.items(),key=lambda x:-x[1][2])[:10]}; R["issues"]=len(getattr(getattr(ed,"_latex_checker",None),"_last_issues",[]) or [])
    acc.clear(); ed.setFocus(); n=ed.lines(); ed.setCursorPosition(n//2,0); spin(.3)
    lat=[]; L=Lag(); L.start()
    for pause,save in ((2.0,0),(2.0,0),(3.3,0),(0.2,1),(2.0,1),(1.6,0),(3.3,1),(2.2,0)):
        if save: ed._latex_checker.force_check()
        for ch in "alpha beta gamma ":
            t=time.perf_counter(); QTest.keyClick(ed,ch); app.processEvents(); d=(time.perf_counter()-t)*1000; lat.append(d); spin(max(0.001,0.09-d/1000))
        spin(pause)
    lat.sort(); k=len(lat)
    R.update(file=f.name,size=size if False else f.stat().st_size,key={"p50":round(lat[k//2],1),"p95":round(lat[int(k*.95)],1),"p99":round(lat[int(k*.99)],1),"max":round(lat[-1],1)},over50=sum(x>50 for x in lat),over100=sum(x>100 for x in lat),n=k,lag=L.stop(),type_fn={k:[v[0],round(v[1]),round(v[2])] for k,v in sorted(acc.items(),key=lambda x:-x[1][2])[:10]},issues_after=len(getattr(ed._latex_checker,"_last_issues",[]) or []))
elif kind=="idle":
    spin(3.0); c0=cpu(); wake0=P.num_ctx_switches().voluntary
    t=time.perf_counter(); app_exec_for=30
    QTimer.singleShot(app_exec_for*1000,app.quit); app.exec()
    d=time.perf_counter()-t
    R.update(idle_cpu_pct=round((cpu()-c0)/d*100,2),ctx_per_s=round((P.num_ctx_switches().voluntary-wake0)/d,1),rss=rss())
elif kind=="ops":
    # costly one-shots on a large doc
    f=Path(sys.argv[2]); win.open_files([f]); ed=win._tab_manager.current_editor(); size=f.stat().st_size
    while ed.length()<size*0.98: app.processEvents(); time.sleep(0.001)
    spin(2.0)
    def tm(name,fn):
        t=time.perf_counter(); fn(); app.processEvents(); R[name]=round((time.perf_counter()-t)*1000,1)
    tm("text()",ed.text); tm("get_content",ed.get_content)
    tm("selectAll+info",lambda:(ed.selectAll(),ed._emit_selection_info())); ed.setCursorPosition(0,0)
    from core.file_manager import FileManager
    raw=f.read_bytes(); tm("decode_bytes",lambda:FileManager.decode_bytes(raw))
    tm("get_bookmarks",ed.get_bookmarks)
    tm("scroll_mid",lambda:ed.setFirstVisibleLine(ed.lines()//2)); tm("scroll_end",lambda:ed.setFirstVisibleLine(ed.lines()-5))
    tm("wrap_on",lambda:(ed.set_word_wrap(True))); spin(.1); tm("wrap_off",lambda:(ed.set_word_wrap(False)))
    try:
        tmp=Path(os.environ["HOME"])/("save_"+f.name); ed.file_path=tmp
        tm("save(write)",lambda:FileManager.write(tmp,ed.get_content(),"UTF-8"))
    except Exception as e: R["saveerr"]=str(e)
    R["rss"]=rss()
print("BENCH="+json.dumps(R),flush=True)
os._exit(0)
