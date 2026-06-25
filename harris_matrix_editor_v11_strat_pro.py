
import json, zipfile, re, copy, math, xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from pathlib import Path
from collections import defaultdict, deque, Counter

APP_TITLE = "Harris Matrix Editor V11 STRAT PRO"
LEFT, TOP = 340, 105
BOX_W, BOX_H = 126, 46
X_STEP, Y_STEP = 172, 104

PALETTE = {
    "Structural": "#B9D7EF",
    "Deposit": "#F8E8A8",
    "Cut": "#F4B2B2",
    "Fill": "#F7C986",
    "Surface": "#C7E9BF",
    "Natural": "#D8D8D8",
    "Geology": "#CFCFCF",
    "Unexcavated": "#C5C5C5",
    "Same context": "#F3B8C8",
    "Unknown": "#F3F3F3",
}

def pnum(s):
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else 999999

def norm_id(cid):
    cid = str(cid).strip()
    if cid == "F!10":
        return "F110"
    if cid in ("F8","F29"):
        return "F8=F29"
    if cid in ("U",):
        return "Unexcavated"
    if cid in ("G","Natural","Geology"):
        return "Natural/Geology"
    return cid

def norm_type(t):
    if not t:
        return "Unknown"
    s = str(t).lower()
    if "struct" in s or "wall" in s or "stone" in s or "sten" in s or "bygning" in s:
        return "Structural"
    if "fill" in s:
        return "Fill"
    if "cut" in s:
        return "Cut"
    if "surface" in s or "interface" in s or "top" in s:
        return "Surface"
    if "unexcavated" in s:
        return "Unexcavated"
    if "geology" in s:
        return "Geology"
    if "natural" in s:
        return "Natural"
    if "deposit" in s or "layer" in s or "lag" in s:
        return "Deposit"
    if "=" in str(t):
        return "Same context"
    return str(t) if str(t) in PALETTE else "Unknown"

def box_width(label):
    return max(BOX_W, min(260, len(str(label))*8 + 48))

def esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1720x1000")
        self.nodes = {}
        self.edges = []
        self.groups = []
        self.phases = []
        self.selected = set()
        self.selected_group = None
        self.selected_phase = None
        self.drag = (0,0)
        self.resizing_group = False
        self.moving_group = False
        self.moving_phase = False
        self.zoom = 1.0
        self.undo_stack = []
        self.clipboard_warning = False
        self._ui()
        self.new_project()

    def _ui(self):
        top = tk.Frame(self); top.pack(fill=tk.X)
        for text, cmd in [
            ("Ny/Ryd flade", self.clear_canvas),
            ("Åbn HMCX", self.open_hmcx),
            ("Gem HMCX", self.save_hmcx),
            ("Åbn JSON", self.open_json),
            ("Gem JSON", self.save_json),
            ("Tilføj context", self.add_context),
            ("Tilføj relation", self.add_relation),
            ("Tilføj struktur-boks", self.add_group),
            ("Tilføj fase-linje", self.add_phase),
            ("Auto-layout STRAT", self.auto_layout),
            ("Auto-fit faser/bokse", self.auto_annotations),
            ("Slet valgte", self.delete_selected),
            ("Fortryd", self.undo),
            ("Kontroller", self.validate_show),
            ("PDF", self.export_pdf),
            ("PNG", self.export_png),
            ("SVG", self.export_svg),
            ("Graph", self.export_graph),
            ("Zoom +", lambda:self.set_zoom(self.zoom*1.15)),
            ("Zoom -", lambda:self.set_zoom(self.zoom/1.15)),
            ("Fit", self.fit),
            ("Søg", self.search),
        ]:
            tk.Button(top, text=text, command=cmd).pack(side=tk.LEFT, padx=1, pady=2)

        main = tk.PanedWindow(self, orient=tk.HORIZONTAL); main.pack(fill=tk.BOTH, expand=True)
        left = tk.Frame(main); main.add(left, stretch="always")
        self.canvas = tk.Canvas(left, bg="white", scrollregion=(0,0,8600,5400))
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ys = tk.Scrollbar(left, orient=tk.VERTICAL, command=self.canvas.yview); ys.pack(side=tk.RIGHT, fill=tk.Y)
        xs = tk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.canvas.xview); xs.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)

        right = tk.Frame(main, width=410); main.add(right)
        tk.Label(right, text="V11 STRAT Inspector", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=8, pady=6)
        self.info = tk.Text(right, height=13, width=48)
        self.info.pack(fill=tk.X, padx=8)
        tk.Button(right, text="Opdater valgt", command=self.update_selected).pack(fill=tk.X, padx=8, pady=3)

        tk.Label(right, text="Relationer", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=8, pady=6)
        self.rels = tk.Listbox(right, height=14, selectmode=tk.EXTENDED)
        self.rels.pack(fill=tk.BOTH, expand=True, padx=8)
        tk.Button(right, text="Slet valgte relationer", command=self.delete_relation).pack(fill=tk.X, padx=8, pady=3)

        tk.Label(right, text="Harris-princip", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=8, pady=6)
        self.legend = tk.Canvas(right, height=275, bg="#FBFBFB")
        self.legend.pack(fill=tk.X, padx=8)
        self.draw_legend()

        self.status = tk.StringVar(value="V11 STRAT klar")
        tk.Label(self, textvariable=self.status, anchor="w").pack(fill=tk.X)

        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag_motion)
        self.canvas.bind("<Double-Button-1>", self.double)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<ButtonPress-3>", self.pan_start)
        self.canvas.bind("<B3-Motion>", self.pan_move)

    def draw_legend(self):
        self.legend.delete("all")
        y=10
        for k,c in PALETTE.items():
            self.legend.create_rectangle(10,y,34,y+16,fill=c,outline="#555")
            self.legend.create_text(44,y+8,text=k,anchor="w",font=("Segoe UI",9))
            y += 21
        y += 8
        self.legend.create_text(10,y,text="Yngre contexts placeres højere.",anchor="w",font=("Segoe UI",9,"bold")); y += 19
        self.legend.create_text(10,y,text="Ældre contexts placeres lavere.",anchor="w",font=("Segoe UI",9)); y += 18
        self.legend.create_text(10,y,text="Urelaterede contexts tvinges ikke i kæde.",anchor="w",font=("Segoe UI",9)); y += 18
        self.legend.create_text(10,y,text="Parallelle grene deles og samles.",anchor="w",font=("Segoe UI",9)); y += 18
        self.legend.create_text(10,y,text="Faser/bokse er grafik, ikke relationer.",anchor="w",font=("Segoe UI",9))

    def sx(self,x): return x*self.zoom
    def sy(self,y): return y*self.zoom
    def ux(self,x): return x/self.zoom
    def uy(self,y): return y/self.zoom

    def push_undo(self):
        self.undo_stack.append(copy.deepcopy((self.nodes, self.edges, self.groups, self.phases)))
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def undo(self):
        if not self.undo_stack:
            messagebox.showinfo("Fortryd", "Der er ikke noget at fortryde.")
            return
        self.nodes, self.edges, self.groups, self.phases = self.undo_stack.pop()
        self.selected=set(); self.selected_group=None; self.selected_phase=None
        self.draw()

    def clear_canvas(self):
        if self.nodes and not messagebox.askyesno("Ryd flade", "Ryd hele fladen?"):
            return
        self.push_undo()
        self.nodes={}; self.edges=[]; self.groups=[]; self.phases=[]; self.selected=set()
        self.draw()
        self.status.set("Fladen er ryddet")

    def new_project(self):
        self.nodes = {
            "Topsoil":{"id":"Topsoil","label":"Topsoil","type":"Surface","x":LEFT+350,"y":TOP,"w":150,"h":46},
            "Unexcavated":{"id":"Unexcavated","label":"Unexcavated","type":"Unexcavated","x":LEFT+310,"y":TOP+420,"w":230,"h":46},
            "Natural/Geology":{"id":"Natural/Geology","label":"Natural/Geology","type":"Geology","x":LEFT+295,"y":TOP+530,"w":260,"h":46},
        }
        self.edges=[{"source":"Topsoil","target":"Unexcavated"},{"source":"Unexcavated","target":"Natural/Geology"}]
        self.groups=[]; self.phases=[]; self.selected=set()
        self.draw()

    def is_top(self,nid):
        txt=(nid+" "+str(self.nodes.get(nid,{}).get("label",""))).lower()
        return nid.upper() in ("T","TOP","TOPSOIL") or "topsoil" in txt or "græstørv" in txt or "top surface" in txt

    def is_unexcavated(self,nid):
        txt=(nid+" "+str(self.nodes.get(nid,{}).get("label",""))).lower()
        return nid=="Unexcavated" or norm_type(self.nodes.get(nid,{}).get("type"))=="Unexcavated" or "unexcavated" in txt

    def is_geology(self,nid):
        txt=(nid+" "+str(self.nodes.get(nid,{}).get("label",""))).lower()
        return nid=="Natural/Geology" or norm_type(self.nodes.get(nid,{}).get("type")) in ("Natural","Geology") or "natural" in txt or "geology" in txt

    def is_bottom(self,nid):
        return self.is_unexcavated(nid) or self.is_geology(nid)

    def draw(self):
        self.canvas.delete("all")
        for y in range(80,5000,Y_STEP):
            self.canvas.create_line(self.sx(140),self.sy(y),self.sx(8300),self.sy(y),fill="#F7F7F7")
        for i,p in enumerate(self.phases):
            col = "#A58E42" if i != self.selected_phase else "#C22"
            self.canvas.create_line(self.sx(150),self.sy(p["y"]),self.sx(8200),self.sy(p["y"]),fill=col,dash=(10,6),width=1.4,tags=("phase",str(i)))
            self.canvas.create_text(self.sx(165),self.sy(p["y"]-8),text=p.get("name","Fase"),anchor="sw",fill=col,font=("Segoe UI",10,"bold"),tags=("phase",str(i)))
        for i,g in enumerate(self.groups):
            col = "#5D84AF" if i != self.selected_group else "#C22"
            self.canvas.create_rectangle(self.sx(g["x"]),self.sy(g["y"]),self.sx(g["x"]+g["w"]),self.sy(g["y"]+g["h"]),outline=col,dash=(7,5),width=2,tags=("group",str(i)))
            self.canvas.create_text(self.sx(g["x"]+10),self.sy(g["y"]+18),text=g.get("name","Konstruktion"),anchor="w",fill=col,font=("Segoe UI",10,"bold"),tags=("group",str(i)))
            self.canvas.create_rectangle(self.sx(g["x"]+g["w"]-12),self.sy(g["y"]+g["h"]-12),self.sx(g["x"]+g["w"]+2),self.sy(g["y"]+g["h"]+2),fill=col,outline="",tags=("gresize",str(i)))
        for e in self.edges:
            if e["source"] in self.nodes and e["target"] in self.nodes:
                self.draw_edge(e)
        for n in self.nodes.values():
            self.draw_node(n)
        self.update_panel()

    def draw_edge(self,e):
        a,b=self.nodes[e["source"]],self.nodes[e["target"]]
        x1=a["x"]+a.get("w",BOX_W)/2; y1=a["y"]+a.get("h",BOX_H)
        x2=b["x"]+b.get("w",BOX_W)/2; y2=b["y"]
        mid=(y1+y2)/2
        self.canvas.create_line(self.sx(x1),self.sy(y1),self.sx(x1),self.sy(mid),self.sx(x2),self.sy(mid),self.sx(x2),self.sy(y2),fill="#222",width=max(1,int(1.15*self.zoom)),capstyle=tk.ROUND,joinstyle=tk.ROUND)

    def draw_node(self,n):
        x,y,w,h=n["x"],n["y"],n.get("w",BOX_W),n.get("h",BOX_H)
        col=PALETTE.get(norm_type(n.get("type")),PALETTE["Unknown"])
        outline="#C22" if n["id"] in self.selected else "#333"
        width=2.2 if n["id"] in self.selected else 1.3
        self.canvas.create_rectangle(self.sx(x),self.sy(y),self.sx(x+w),self.sy(y+h),fill=col,outline=outline,width=width,tags=("node",n["id"]))
        label=str(n.get("label",n["id"]))
        maxchars=max(8,int(w/7))
        if len(label)>maxchars: label=label[:maxchars-1]+"…"
        self.canvas.create_text(self.sx(x+w/2),self.sy(y+h/2),text=label,font=("Segoe UI",8,"bold"),tags=("node",n["id"]))

    def hit(self,event):
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x,y,x,y)):
            tags=self.canvas.gettags(item)
            if "node" in tags:
                for t in tags:
                    if t in self.nodes: return ("node",t)
            if "gresize" in tags:
                for t in tags:
                    if t.isdigit(): return ("gresize",int(t))
            if "group" in tags:
                for t in tags:
                    if t.isdigit(): return ("group",int(t))
            if "phase" in tags:
                for t in tags:
                    if t.isdigit(): return ("phase",int(t))
        return None,None

    def press(self,event):
        kind,val=self.hit(event)
        self.resizing_group=self.moving_group=self.moving_phase=False
        x,y=self.ux(self.canvas.canvasx(event.x)),self.uy(self.canvas.canvasy(event.y))
        if kind=="node":
            if event.state & 0x0004:  # Ctrl multi-select
                if val in self.selected: self.selected.remove(val)
                else: self.selected.add(val)
            else:
                self.selected={val}
            n=self.nodes[val]; self.drag=(x-n["x"],y-n["y"])
            self.selected_group=None; self.selected_phase=None
        elif kind=="gresize":
            self.selected=set(); self.selected_group=val; self.resizing_group=True
            g=self.groups[val]; self.drag=(x-(g["x"]+g["w"]),y-(g["y"]+g["h"]))
        elif kind=="group":
            self.selected=set(); self.selected_group=val; self.moving_group=True
            g=self.groups[val]; self.drag=(x-g["x"],y-g["y"])
        elif kind=="phase":
            self.selected=set(); self.selected_phase=val; self.moving_phase=True
            p=self.phases[val]; self.drag=(0,y-p["y"])
        else:
            if not (event.state & 0x0004): self.selected=set()
            self.selected_group=None; self.selected_phase=None
        self.draw()

    def drag_motion(self,event):
        if not (self.selected or self.selected_group is not None or self.selected_phase is not None):
            return
        if not hasattr(self, "_drag_started"):
            self.push_undo(); self._drag_started=True
        x,y=self.ux(self.canvas.canvasx(event.x)),self.uy(self.canvas.canvasy(event.y))
        dx,dy=self.drag
        if self.selected:
            primary=next(iter(self.selected))
            nx=round(x-dx); ny=round(y-dy)
            odx=nx-self.nodes[primary]["x"]; ody=ny-self.nodes[primary]["y"]
            for nid in self.selected:
                self.nodes[nid]["x"]+=odx; self.nodes[nid]["y"]+=ody
        elif self.selected_group is not None:
            g=self.groups[self.selected_group]
            if self.resizing_group:
                g["w"]=max(110,round(x-dx-g["x"])); g["h"]=max(68,round(y-dy-g["y"]))
            elif self.moving_group:
                g["x"]=round(x-dx); g["y"]=round(y-dy)
        elif self.selected_phase is not None:
            self.phases[self.selected_phase]["y"]=round(y-dy)
        self.draw()
        if hasattr(self, "_drag_started"):
            delattr(self, "_drag_started")

    def double(self,event):
        kind,val=self.hit(event)
        if kind=="node":
            self.push_undo()
            n=self.nodes[val]
            lab=simpledialog.askstring("Label","Label:",initialvalue=n.get("label",val),parent=self)
            if lab is None: return
            typ=simpledialog.askstring("Feature Type","Structural / Deposit / Cut / Fill / Surface / Natural / Geology / Unexcavated:",initialvalue=n.get("type","Deposit"),parent=self)
            n["label"]=lab; n["type"]=norm_type(typ); n["w"]=box_width(lab)
        elif kind=="group":
            self.push_undo()
            name=simpledialog.askstring("Struktur-boks","Navn:",initialvalue=self.groups[val].get("name",""),parent=self)
            if name is not None: self.groups[val]["name"]=name
        elif kind=="phase":
            self.push_undo()
            name=simpledialog.askstring("Fase","Navn:",initialvalue=self.phases[val].get("name",""),parent=self)
            if name is not None: self.phases[val]["name"]=name
        self.draw()

    def wheel(self,event): self.set_zoom(self.zoom*(1.08 if event.delta>0 else 1/1.08))
    def set_zoom(self,z): self.zoom=max(0.28,min(2.6,z)); self.draw()
    def pan_start(self,event): self.pan=(event.x,event.y)
    def pan_move(self,event):
        dx=event.x-self.pan[0]; dy=event.y-self.pan[1]
        self.canvas.xview_scroll(int(-dx/2),"units"); self.canvas.yview_scroll(int(-dy/2),"units")
        self.pan=(event.x,event.y)

    def update_panel(self):
        self.info.delete("1.0",tk.END)
        if len(self.selected)==1:
            nid=next(iter(self.selected)); n=self.nodes[nid]
            self.info.insert("1.0",f"id={n['id']}\nlabel={n.get('label','')}\ntype={n.get('type','')}\nx={n.get('x',0)}\ny={n.get('y',0)}\nw={n.get('w',BOX_W)}\n")
        elif len(self.selected)>1:
            self.info.insert("1.0",f"{len(self.selected)} contexts valgt\nSlet valgte-knappen sletter alle.\nCtrl+klik vælger/fravælger.\n")
        elif self.selected_group is not None:
            g=self.groups[self.selected_group]
            self.info.insert("1.0",f"group={g.get('name','')}\nx={g.get('x',0)}\ny={g.get('y',0)}\nw={g.get('w',0)}\nh={g.get('h',0)}\n")
        elif self.selected_phase is not None:
            p=self.phases[self.selected_phase]
            self.info.insert("1.0",f"phase={p.get('name','')}\ny={p.get('y',0)}\n")
        self.rels.delete(0,tk.END)
        if len(self.selected)==1:
            nid=next(iter(self.selected))
            for i,e in enumerate(self.edges):
                if e["source"]==nid or e["target"]==nid:
                    self.rels.insert(tk.END,f"{i}: {e['source']} over {e['target']}")

    def update_selected(self):
        self.push_undo()
        d={}
        for line in self.info.get("1.0",tk.END).splitlines():
            if "=" in line:
                k,v=line.split("=",1); d[k.strip()]=v.strip()
        if len(self.selected)==1:
            old=next(iter(self.selected)); n=self.nodes[old]
            new=norm_id(d.get("id",old))
            if new!=old:
                if new in self.nodes:
                    messagebox.showerror("Fejl","ID findes allerede"); return
                self.nodes[new]=self.nodes.pop(old); self.nodes[new]["id"]=new
                for e in self.edges:
                    if e["source"]==old: e["source"]=new
                    if e["target"]==old: e["target"]=new
                self.selected={new}; n=self.nodes[new]
            if "label" in d: n["label"]=d["label"]; n["w"]=box_width(d["label"])
            if "type" in d: n["type"]=norm_type(d["type"])
            for k in ("x","y","w"):
                if k in d:
                    try: n[k]=float(d[k])
                    except: pass
        elif self.selected_group is not None:
            g=self.groups[self.selected_group]
            if "group" in d: g["name"]=d["group"]
            for k in ("x","y","w","h"):
                if k in d:
                    try: g[k]=float(d[k])
                    except: pass
        elif self.selected_phase is not None:
            p=self.phases[self.selected_phase]
            if "phase" in d: p["name"]=d["phase"]
            if "y" in d:
                try: p["y"]=float(d["y"])
                except: pass
        self.draw()

    def add_context(self):
        cid=norm_id(simpledialog.askstring("Ny context","Context ID:",parent=self) or "")
        if not cid: return
        if cid in self.nodes:
            messagebox.showerror("Fejl","Findes allerede"); return
        typ=simpledialog.askstring("Feature Type","Structural / Deposit / Cut / Fill:",initialvalue="Deposit",parent=self) or "Deposit"
        self.push_undo()
        self.nodes[cid]={"id":cid,"label":cid,"type":norm_type(typ),"x":LEFT,"y":TOP,"w":box_width(cid),"h":BOX_H}
        self.draw()

    def add_relation(self):
        a=norm_id(simpledialog.askstring("Relation","Yngre / over:",parent=self) or "")
        b=norm_id(simpledialog.askstring("Relation","Ældre / under:",parent=self) or "")
        if not a or not b: return
        self.push_undo()
        self.ensure(a); self.ensure(b)
        if not any(e["source"]==a and e["target"]==b for e in self.edges):
            self.edges.append({"source":a,"target":b})
        self.draw()

    def ensure(self,cid):
        if cid not in self.nodes:
            self.nodes[cid]={"id":cid,"label":cid,"type":"Unknown","x":LEFT,"y":TOP,"w":box_width(cid),"h":BOX_H}

    def add_group(self):
        name=simpledialog.askstring("Struktur/konstruktion","Navn:",initialvalue="Konstruktion",parent=self)
        if name:
            self.push_undo()
            self.groups.append({"name":name,"x":LEFT+140,"y":TOP+170,"w":430,"h":220})
            self.draw()

    def add_phase(self):
        name=simpledialog.askstring("Fase-linje","Navn:",initialvalue="Fase",parent=self)
        if name:
            self.push_undo()
            self.phases.append({"name":name,"y":TOP+260})
            self.draw()

    def delete_selected(self):
        if not (self.selected or self.selected_group is not None or self.selected_phase is not None):
            return
        self.push_undo()
        if self.selected:
            for nid in list(self.selected):
                if nid in self.nodes:
                    del self.nodes[nid]
            self.edges=[e for e in self.edges if e["source"] not in self.selected and e["target"] not in self.selected]
            self.selected=set()
        elif self.selected_group is not None:
            del self.groups[self.selected_group]; self.selected_group=None
        elif self.selected_phase is not None:
            del self.phases[self.selected_phase]; self.selected_phase=None
        self.draw()

    def delete_relation(self):
        selected=list(self.rels.curselection())
        if not selected: return
        self.push_undo()
        idxs=sorted([int(self.rels.get(i).split(":",1)[0]) for i in selected], reverse=True)
        for idx in idxs:
            if 0 <= idx < len(self.edges): del self.edges[idx]
        self.draw()

    # ---- Harris STRAT layout core ----
    def strat_edges(self):
        """Return clean Harris edges: younger/above -> older/below.
        Rules:
        - Top can only be source.
        - Geology/Natural can only be final bottom.
        - Unexcavated is below all excavated contexts, but above Natural/Geology.
        - Unrelated branches stay parallel; missing tops/bottoms are anchored only at boundaries.
        """
        clean=[]
        for e in self.edges:
            a,b=e["source"],e["target"]
            if a not in self.nodes or b not in self.nodes or a==b:
                continue
            if self.is_geology(a):
                continue
            if self.is_top(b):
                continue
            if self.is_unexcavated(a) and not self.is_geology(b):
                continue
            clean.append((a,b))
        clean=list(dict.fromkeys(clean))

        tops=[n for n in self.nodes if self.is_top(n)]
        unex=[n for n in self.nodes if self.is_unexcavated(n)]
        geol=[n for n in self.nodes if self.is_geology(n)]
        top=tops[0] if tops else None
        u=unex[0] if unex else None
        g=geol[0] if geol else None

        indeg=Counter(b for a,b in clean)
        out=Counter(a for a,b in clean)
        for n in self.nodes:
            if n in (top,u,g): continue
            if top and indeg[n]==0:
                clean.append((top,n))
            if u and out[n]==0:
                clean.append((n,u))
        if u and g:
            clean=[(a,b) for a,b in clean if not (a==u and b!=g)]
            if (u,g) not in clean:
                clean.append((u,g))
        return list(dict.fromkeys(clean))

    def remove_cycles_for_layout(self, edges):
        edges=list(edges)
        removed=[]
        while True:
            g=defaultdict(list)
            for a,b in edges: g[a].append(b)
            temp=set(); perm=set(); cycle=[]
            def visit(n,path):
                nonlocal cycle
                if cycle: return
                if n in temp:
                    cycle=path[path.index(n):]+[n] if n in path else path+[n]
                    return
                if n in perm: return
                temp.add(n)
                for m in g.get(n,[]): visit(m,path+[n])
                temp.remove(n); perm.add(n)
            for n in self.nodes:
                visit(n,[])
                if cycle: break
            if not cycle: break
            cyc_edges=list(zip(cycle,cycle[1:]))
            # Prefer to remove a suspicious back-edge, often entered by mistake.
            cand=cyc_edges[-1]
            for e in cyc_edges:
                if pnum(e[0]) > pnum(e[1]):
                    cand=e
                    break
            if cand in edges:
                edges.remove(cand); removed.append(cand)
            else:
                break
        return edges, removed

    def compute_levels(self, edges):
        """Harris levels:
        level = 1 + max(level of all younger contexts).
        This creates parallel branches and mergers like examples A/B/C.
        """
        edges, removed = self.remove_cycles_for_layout(edges)
        children=defaultdict(list)
        indeg={n:0 for n in self.nodes}
        for a,b in edges:
            children[a].append(b)
            indeg[b]=indeg.get(b,0)+1
            indeg.setdefault(a,0)
        q=deque([n for n,d in indeg.items() if d==0])
        level={n:0 for n in self.nodes}
        seen=set()
        while q:
            n=q.popleft(); seen.add(n)
            for m in children[n]:
                level[m]=max(level[m], level[n]+1)
                indeg[m]-=1
                if indeg[m]==0: q.append(m)
        for n in self.nodes:
            if n not in seen and not self.is_top(n) and not self.is_unexcavated(n) and not self.is_geology(n):
                level[n]=max(1, max(level.values())//2)
        max_exc=max([level[n] for n in self.nodes if not self.is_unexcavated(n) and not self.is_geology(n)] or [0])
        for n in self.nodes:
            if self.is_top(n): level[n]=0
            elif self.is_unexcavated(n): level[n]=max_exc+2
            elif self.is_geology(n): level[n]=max_exc+3
            else: level[n]=max(1, level[n])
        return level, edges, removed

    def order_within_levels(self, level, edges):
        """Try to keep branches vertical and mergers visually balanced."""
        buckets=defaultdict(list)
        for n,l in level.items(): buckets[l].append(n)
        parents=defaultdict(list)
        children=defaultdict(list)
        for a,b in edges:
            parents[b].append(a); children[a].append(b)
        positions={}
        for lev in sorted(buckets):
            arr=buckets[lev]
            def bary(n):
                ps=[positions[p] for p in parents[n] if p in positions]
                if ps: return sum(ps)/len(ps)
                return pnum(n)/1000.0
            arr=sorted(arr, key=lambda n:(bary(n), 0 if n in ("F14","F21","F22") else 1, pnum(n), n))
            for i,n in enumerate(arr):
                positions[n]=i
            buckets[lev]=arr
        # second pass bottom-up for merge balance
        for lev in sorted(buckets, reverse=True):
            arr=buckets[lev]
            def cbary(n):
                cs=[positions[c] for c in children[n] if c in positions]
                if cs: return sum(cs)/len(cs)
                return positions.get(n,0)
            arr=sorted(arr, key=lambda n:(cbary(n), positions.get(n,0), pnum(n), n))
            for i,n in enumerate(arr): positions[n]=i
            buckets[lev]=arr
        return buckets

    def auto_layout(self):
        self.push_undo()
        clean=self.strat_edges()
        level, edges_for_layout, removed = self.compute_levels(clean)
        buckets=self.order_within_levels(level, edges_for_layout)
        for lev in sorted(buckets):
            arr=buckets[lev]
            for i,nid in enumerate(arr):
                self.nodes[nid]["x"]=LEFT+i*X_STEP
                self.nodes[nid]["y"]=TOP+lev*Y_STEP
                self.nodes[nid]["w"]=box_width(self.nodes[nid].get("label",nid))
        self.auto_annotations(level)
        self.draw(); self.fit()
        msg="Auto-layout STRAT færdig"
        if removed:
            msg += f" — ignorerede {len(removed)} cykel-relation(er) i layout"
        self.status.set(msg)

    def auto_annotations(self, level=None):
        if level is None:
            level={n:int((self.nodes[n]["y"]-TOP)/Y_STEP) for n in self.nodes}
        if not self.phases:
            maxlev=max(level.values()) if level else 7
            self.phases=[
                {"name":"Sen fase", "y":TOP+Y_STEP*2.5},
                {"name":"Mellem fase", "y":TOP+Y_STEP*(maxlev*0.55)},
                {"name":"Tidlig fase", "y":TOP+Y_STEP*(maxlev-0.75)},
            ]
        if not self.groups:
            for name,members in {
                "Bygning / konstruktion F14": ["F14","F21","F5"],
                "F22 stenrække": ["F22"],
                "Gærde / struktur F7": ["F7"],
            }.items():
                present=[self.nodes[m] for m in members if m in self.nodes]
                if present:
                    self.groups.append(self.box_around(name,present))
        else:
            # keep user-created boxes; only auto-fit known boxes by exact names
            for g in self.groups:
                members=[]
                if "F14" in g.get("name","") or "Bygning" in g.get("name",""):
                    members=[self.nodes[m] for m in ("F14","F21","F5") if m in self.nodes]
                elif "F22" in g.get("name",""):
                    members=[self.nodes[m] for m in ("F22",) if m in self.nodes]
                elif "F7" in g.get("name","") or "Gærde" in g.get("name",""):
                    members=[self.nodes[m] for m in ("F7",) if m in self.nodes]
                if members:
                    g.update(self.box_around(g.get("name","Konstruktion"),members))
        return level

    def box_around(self,name,nodes):
        minx=min(n["x"] for n in nodes)-46
        miny=min(n["y"] for n in nodes)-60
        maxx=max(n["x"]+n.get("w",BOX_W) for n in nodes)+46
        maxy=max(n["y"]+n.get("h",BOX_H) for n in nodes)+46
        return {"name":name,"x":minx,"y":miny,"w":maxx-minx,"h":maxy-miny}

    def validate_show(self):
        edges=self.strat_edges()
        _, _, removed = self.compute_levels(edges)
        problems=[]
        if removed:
            problems.append("Cykler/back-edges i layout: " + ", ".join(f"{a}->{b}" for a,b in removed))
        if not problems:
            messagebox.showinfo("Kontrol","✓ Ingen stratigrafiske cykler fundet i layout-grafen")
        else:
            messagebox.showwarning("Kontrol","\n".join(problems))

    # ---- import/export ----
    def open_hmcx(self):
        if self.nodes and not messagebox.askyesno("Åbn HMCX", "Ryd fladen og åbn ny HMCX?"):
            return
        p=filedialog.askopenfilename(filetypes=[("HMCX","*.hmcx"),("All files","*.*")])
        if p:
            self.push_undo()
            self.load_hmcx(p)

    def load_hmcx(self,path):
        try:
            with zipfile.ZipFile(path) as z:
                names=z.namelist()
                xmlname="matrix.xml" if "matrix.xml" in names else next(n for n in names if n.endswith(".xml"))
                xml=z.read(xmlname).decode("utf-8",errors="ignore")
                meta=z.read("project.xml").decode("utf-8",errors="ignore") if "project.xml" in names else ""
        except Exception as e:
            messagebox.showerror("HMCX fejl",str(e)); return
        self.nodes={}; self.edges=[]; self.groups=[]; self.phases=[]; self.selected=set()
        root=ET.fromstring(xml); gid={}
        for el in root.iter():
            if el.tag.endswith("node"):
                graphid=el.attrib.get("id","")
                for sub in el.iter():
                    if sub.tag.endswith("hmcnode"):
                        cid=norm_id(sub.attrib.get("id") or graphid)
                        gid[graphid]=cid
                        x=float(sub.attrib.get("x","0") or 0); y=float(sub.attrib.get("y","0") or 0)
                        typ=norm_type(sub.attrib.get("type","Deposit"))
                        if cid=="Unexcavated": typ="Unexcavated"
                        if cid=="Natural/Geology": typ="Geology"
                        self.nodes[cid]={"id":cid,"label":cid,"type":typ,"x":x,"y":y,"w":box_width(cid),"h":BOX_H}
                        break
            elif el.tag.endswith("edge"):
                a=el.attrib.get("source"); b=el.attrib.get("target")
                if a and b:
                    a,b=norm_id(gid.get(a,a)),norm_id(gid.get(b,b))
                    if a!=b and not any(e["source"]==a and e["target"]==b for e in self.edges):
                        self.edges.append({"source":a,"target":b})
        for m in re.finditer(r'<phase name="([^"]+)" y="([^"]+)"',meta):
            self.phases.append({"name":m.group(1),"y":float(m.group(2))})
        for m in re.finditer(r'<group name="([^"]+)" x="([^"]+)" y="([^"]+)" w="([^"]+)" h="([^"]+)"',meta):
            self.groups.append({"name":m.group(1),"x":float(m.group(2)),"y":float(m.group(3)),"w":float(m.group(4)),"h":float(m.group(5))})
        self.auto_layout()
        self.status.set(f"Åbnede {Path(path).name}: {len(self.nodes)} contexts, {len(self.edges)} relationer")

    def open_json(self):
        if self.nodes and not messagebox.askyesno("Åbn JSON", "Ryd fladen og åbn ny JSON?"):
            return
        p=filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if p:
            self.push_undo()
            d=json.load(open(p,encoding="utf-8"))
            self.nodes={n["id"]:n for n in d.get("nodes",[])}
            self.edges=d.get("edges",[])
            self.groups=d.get("groups",[])
            self.phases=d.get("phases",[])
            self.selected=set()
            self.draw(); self.fit()

    def save_json(self):
        p=filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("JSON","*.json")])
        if p:
            json.dump({"nodes":list(self.nodes.values()),"edges":self.edges,"groups":self.groups,"phases":self.phases},open(p,"w",encoding="utf-8"),ensure_ascii=False,indent=2)

    def hmc_type(self,t):
        t=norm_type(t)
        if t=="Surface": return "SURFACE"
        if t=="Unexcavated": return "UNEXCAVATED"
        if t in ("Geology","Natural"): return "GEOLOGY"
        if t=="Cut": return "SURFACE"
        return "DEPOSIT"

    def save_hmcx(self):
        p=filedialog.asksaveasfilename(defaultextension=".hmcx",filetypes=[("HMCX","*.hmcx")])
        if not p: return
        graphml=ET.Element("graphml",{"xmlns":"http://graphml.graphdrawing.org/xmlns/graphml"})
        graph=ET.SubElement(graphml,"graph",{"id":"G","edgedefault":"directed"})
        for nid,n in self.nodes.items():
            node=ET.SubElement(graph,"node",{"id":nid})
            data=ET.SubElement(node,"data",{"key":"d0"})
            ET.SubElement(data,"hmcnode",{"id":nid,"name":str(n.get("label",nid)),"description":"","type":self.hmc_type(n.get("type")),"valid":"true","x":str(n.get("x",0)),"y":str(n.get("y",0)),"layer":"0","index":"0","bookmarked":"false"})
        for i,e in enumerate(self.edges):
            edge=ET.SubElement(graph,"edge",{"id":f"e{i}","source":e["source"],"target":e["target"]})
            data=ET.SubElement(edge,"data",{"key":"d1"})
            ET.SubElement(data,"hmcedge",{"type":"ABOVE","valid":"true"})
        annotations="<annotations>"+"".join(f'<phase name="{esc(p.get("name","Fase"))}" y="{p.get("y",0)}"/>' for p in self.phases)+"".join(f'<group name="{esc(g.get("name","Konstruktion"))}" x="{g.get("x",0)}" y="{g.get("y",0)}" w="{g.get("w",0)}" h="{g.get("h",0)}"/>' for g in self.groups)+"</annotations>"
        with zipfile.ZipFile(p,"w",zipfile.ZIP_DEFLATED) as z:
            z.writestr("project.xml",f'<?xml version="1.0" ?><ProjectProperties Name="Harris Matrix Editor V11 STRAT PRO" Description="V11 phases and structure annotations">{annotations}</ProjectProperties>')
            z.writestr("matrix.xml",ET.tostring(graphml,encoding="utf-8",xml_declaration=True))

    def bounds(self):
        xs=[]; ys=[]
        for n in self.nodes.values():
            xs += [n["x"],n["x"]+n.get("w",BOX_W)]; ys += [n["y"],n["y"]+n.get("h",BOX_H)]
        for g in self.groups:
            xs += [g["x"],g["x"]+g["w"]]; ys += [g["y"],g["y"]+g["h"]]
        for p in self.phases: ys += [p["y"]]
        return (min(xs)-120,min(ys)-120,max(xs)+120,max(ys)+120) if xs else (0,0,1000,700)

    def fit(self):
        minx,miny,maxx,maxy=self.bounds()
        self.zoom=max(0.3,min(1.6,min(1220/max(1,maxx-minx),820/max(1,maxy-miny))))
        self.draw()
        self.canvas.xview_moveto(max(0,self.sx(minx-180)/8600)); self.canvas.yview_moveto(max(0,self.sy(miny-130)/5400))

    def to_svg(self):
        minx,miny,maxx,maxy=self.bounds(); w=maxx-minx; h=maxy-miny
        parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{minx} {miny} {w} {h}"><rect x="{minx}" y="{miny}" width="{w}" height="{h}" fill="white"/>']
        for p in self.phases:
            parts.append(f'<line x1="{minx+24}" y1="{p["y"]}" x2="{maxx-24}" y2="{p["y"]}" stroke="#A58E42" stroke-width="1.4" stroke-dasharray="10 6"/>')
            parts.append(f'<text x="{minx+38}" y="{p["y"]-8}" font-family="Segoe UI, Arial" font-size="13" font-weight="bold" fill="#A58E42">{esc(p.get("name","Fase"))}</text>')
        for g in self.groups:
            parts.append(f'<rect x="{g["x"]}" y="{g["y"]}" width="{g["w"]}" height="{g["h"]}" fill="none" stroke="#5D84AF" stroke-width="2" stroke-dasharray="7 5"/>')
            parts.append(f'<text x="{g["x"]+10}" y="{g["y"]+18}" font-family="Segoe UI, Arial" font-size="13" font-weight="bold" fill="#5D84AF">{esc(g.get("name","Konstruktion"))}</text>')
        for e in self.edges:
            if e["source"] in self.nodes and e["target"] in self.nodes:
                a,b=self.nodes[e["source"]],self.nodes[e["target"]]
                x1=a["x"]+a["w"]/2; y1=a["y"]+a["h"]; x2=b["x"]+b["w"]/2; y2=b["y"]; mid=(y1+y2)/2
                parts.append(f'<polyline points="{x1},{y1} {x1},{mid} {x2},{mid} {x2},{y2}" fill="none" stroke="#222" stroke-width="1.4"/>')
        for n in self.nodes.values():
            c=PALETTE.get(norm_type(n.get("type")),PALETTE["Unknown"])
            parts.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" fill="{c}" stroke="#333" stroke-width="1.2"/>')
            parts.append(f'<text x="{n["x"]+n["w"]/2}" y="{n["y"]+n["h"]/2+4}" text-anchor="middle" font-family="Segoe UI, Arial" font-size="11" font-weight="bold">{esc(n.get("label",n["id"]))}</text>')
        parts.append("</svg>")
        return "\n".join(parts)

    def export_svg(self):
        p=filedialog.asksaveasfilename(defaultextension=".svg",filetypes=[("SVG","*.svg")])
        if p: Path(p).write_text(self.to_svg(),encoding="utf-8")

    def export_png(self):
        p=filedialog.asksaveasfilename(defaultextension=".png",filetypes=[("PNG","*.png")])
        if p:
            import cairosvg
            cairosvg.svg2png(bytestring=self.to_svg().encode("utf-8"),write_to=p,output_width=3000)

    def export_pdf(self):
        p=filedialog.asksaveasfilename(defaultextension=".pdf",filetypes=[("PDF","*.pdf")])
        if not p: return
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A3, landscape
        from reportlab.lib.colors import HexColor, black
        c=canvas.Canvas(p,pagesize=landscape(A3)); pw,ph=landscape(A3)
        minx,miny,maxx,maxy=self.bounds(); scale=min((pw-60)/(maxx-minx),(ph-60)/(maxy-miny))
        def tx(x): return 30+(x-minx)*scale
        def ty(y): return ph-(30+(y-miny)*scale)
        c.setLineWidth(.75)
        for pz in self.phases:
            c.setDash(6,4); c.setStrokeColor(HexColor("#A58E42")); c.line(tx(minx+24),ty(pz["y"]),tx(maxx-24),ty(pz["y"]))
            c.setDash(); c.setFillColor(HexColor("#A58E42")); c.setFont("Helvetica-Bold",8); c.drawString(tx(minx+38),ty(pz["y"]-8),pz.get("name","Fase"))
        c.setStrokeColor(black)
        for e in self.edges:
            if e["source"] in self.nodes and e["target"] in self.nodes:
                a,b=self.nodes[e["source"]],self.nodes[e["target"]]
                x1=a["x"]+a["w"]/2; y1=a["y"]+a["h"]; x2=b["x"]+b["w"]/2; y2=b["y"]; mid=(y1+y2)/2
                for (xa,ya),(xb,yb) in zip([(x1,y1),(x1,mid),(x2,mid)],[(x1,mid),(x2,mid),(x2,y2)]): c.line(tx(xa),ty(ya),tx(xb),ty(yb))
        for g in self.groups:
            c.setDash(5,4); c.setStrokeColor(HexColor("#5D84AF")); c.rect(tx(g["x"]),ty(g["y"]+g["h"]),g["w"]*scale,g["h"]*scale,fill=0,stroke=1)
            c.setDash(); c.setFillColor(HexColor("#5D84AF")); c.setFont("Helvetica-Bold",8); c.drawString(tx(g["x"]+10),ty(g["y"]+18),g.get("name","Konstruktion"))
        c.setDash(); c.setStrokeColor(black)
        for n in self.nodes.values():
            c.setFillColor(HexColor(PALETTE.get(norm_type(n.get("type")),PALETTE["Unknown"])))
            c.rect(tx(n["x"]),ty(n["y"]+n["h"]),n["w"]*scale,n["h"]*scale,fill=1,stroke=1)
            label=str(n.get("label",n["id"])); fs=max(5,min(8.5,(n["w"]*scale)/(max(1,len(label))*0.5)))
            c.setFillColor(black); c.setFont("Helvetica-Bold",fs); c.drawCentredString(tx(n["x"]+n["w"]/2),ty(n["y"]+n["h"]/2)-fs/3,label[:30])
        c.save()

    def export_graph(self):
        p=filedialog.asksaveasfilename(defaultextension=".dot",filetypes=[("Graphviz DOT","*.dot"),("Graph JSON","*.json")])
        if not p: return
        if p.lower().endswith(".json"):
            json.dump({"nodes":list(self.nodes.values()),"edges":self.edges,"groups":self.groups,"phases":self.phases},open(p,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
        else:
            lines=["digraph HarrisMatrix {","  rankdir=TB;","  node [shape=box, fontname=\"Arial\"];"]
            for nid,n in self.nodes.items(): lines.append(f'  "{nid}" [label="{n.get("label",nid)}"];')
            for e in self.edges: lines.append(f'  "{e["source"]}" -> "{e["target"]}";')
            lines.append("}")
            Path(p).write_text("\n".join(lines),encoding="utf-8")

    def search(self):
        q=simpledialog.askstring("Søg","Context:",parent=self)
        if not q: return
        q=q.lower()
        for nid,n in self.nodes.items():
            if q in nid.lower() or q in str(n.get("label","")).lower():
                self.selected={nid}; self.draw()
                self.canvas.xview_moveto(max(0,self.sx(n["x"]-260)/8600)); self.canvas.yview_moveto(max(0,self.sy(n["y"]-200)/5400))
                return

if __name__=="__main__":
    App().mainloop()
