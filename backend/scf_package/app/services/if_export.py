# ruff: noqa: E501  # 内嵌浏览器 CSS/JS 资源，行长规则不适用
"""互动影视导出（增量：InkOS 互动影游核心 · 干净移植）。

把 YIWA 的 StoryGraph 编译成「单个自包含 HTML」，双击即可游玩分支剧情——
对应 Funloom/InkOS 的「导出可玩包」。条件/效果求值在浏览器内嵌 JS 中确定性执行，
与后端 app/runtime/engine.py 的语义一致（变量缺失→False，==/!= 严格类型，add/sub/set）。
"""
import json

_CSS = """
body{font-family:system-ui,'PingFang SC',sans-serif;background:#0b1120;color:#e2e8f0;margin:0;display:flex;justify-content:center;}
#wrap{max-width:680px;width:100%;padding:24px;}
h1{font-size:18px;color:#f472b6;}
h2{font-size:20px;margin:8px 0;}
.desc{color:#94a3b8;white-space:pre-wrap;}
.hud{font-size:12px;color:#64748b;border:1px solid #1e293b;border-radius:8px;padding:6px 10px;margin-bottom:12px;display:inline-block;}
.choices{display:flex;flex-direction:column;gap:8px;margin-top:16px;}
.choice{text-align:left;padding:12px 16px;border:1px solid #334155;border-radius:10px;background:#0f172a;color:#e2e8f0;cursor:pointer;font-size:15px;}
.choice:hover{border-color:#f472b6;}
.deadend{color:#64748b;margin-top:16px;}
.ending{margin-top:20px;padding:16px;border:1px solid #7f1d1d;border-radius:10px;}
.ending-type{font-size:12px;color:#f472b6;text-transform:uppercase;} .ending-title{font-size:22px;margin-top:4px;}
.restart{margin-top:12px;padding:10px 18px;border-radius:8px;background:#f472b6;color:#0b1120;border:none;cursor:pointer;}
"""

_PLAYER_JS = r"""
(function(){
  function h(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  var vars = {};
  (GRAPH.variables||[]).forEach(function(v){ vars[v.name]=v.initial; });
  var nodeById = {}; (GRAPH.nodes||[]).forEach(function(n){ nodeById[n.node_id]=n; });
  var endingByNode = {}; (GRAPH.endings||[]).forEach(function(e){ endingByNode[e.node_id]=e.type; });
  function parseCond(raw){ if(!raw || !String(raw).trim()) return null;
    var m=/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$/.exec(String(raw)); if(!m) return null;
    var v=m[3].trim();
    if((v[0]==="'"&&v[v.length-1]==="'")||(v[0]==='"'&&v[v.length-1]==='"')) v=v.slice(1,-1);
    else if(v==="true") v=true; else if(v==="false") v=false; else if(!isNaN(v)) v=Number(v);
    return {v:m[1],op:m[2],val:v}; }
  function evalCond(c){ if(!c) return true; var v=vars[c.v]; if(v===undefined) return false;
    switch(c.op){ case ">=": return Number(v)>=Number(c.val); case "<=": return Number(v)<=Number(c.val);
      case ">": return Number(v)>Number(c.val); case "<": return Number(v)<Number(c.val);
      case "==": return v===c.val; case "!=": return v!==c.val; } return true; }
  function applyEffects(effects){ (effects||[]).forEach(function(e){
    if(e.op==="add") vars[e.variable]=Number(vars[e.variable]||0)+Number(e.value);
    else if(e.op==="sub") vars[e.variable]=Number(vars[e.variable]||0)-Number(e.value);
    else vars[e.variable]=e.value; }); }
  function visible(node){ return (node.choices||[]).filter(function(c){ return evalCond(parseCond(c.condition)); }); }
  var root=document.getElementById("if-player");
  function hud(){ var s=Object.keys(vars).map(function(k){ return h(k)+":"+h(String(vars[k])); }).join("  ·  ");
    return s?'<div class="hud">'+s+'</div>':''; }
  function render(node){
    if(!node){ root.innerHTML="<p>节点缺失</p>"; return; }
    var html=hud();
    if(node.title) html+='<h2>'+h(node.title)+'</h2>';
    if(node.summary) html+='<p class="desc">'+h(node.summary)+'</p>';
    if(node.kind==="ending"){
      var el = endingByNode[node.node_id]||"neutral";
      var elzw = {good:"好结局",bad:"坏结局",neutral:"普通结局",secret:"隐藏结局"}[el]||"结局";
      html+='<div class="ending"><div class="ending-type">'+elzw+'</div><div class="ending-title">'+h(node.title||"结局")+'</div></div>';
      html+='<button class="restart">重新开始</button>';
      root.innerHTML=html; root.querySelector(".restart").onclick=start; return; }
    var vis=visible(node);
    html+='<div class="choices">';
    vis.forEach(function(c,i){ html+='<button class="choice" data-i="'+i+'">'+h(c.text)+'</button>'; });
    html+='</div>';
    if(vis.length===0) html+='<p class="deadend">（没有可走的选项）</p>';
    root.innerHTML=html;
    Array.prototype.forEach.call(root.querySelectorAll(".choice"), function(btn){
      btn.onclick=function(){ var c=vis[parseInt(btn.getAttribute("data-i"),10)]; applyEffects(c.effects); render(nodeById[c.next_node]); }; });
  }
  function start(){ vars={}; (GRAPH.variables||[]).forEach(function(v){ vars[v.name]=v.initial; });
    var s=(GRAPH.nodes||[]).filter(function(n){return n.node_id===GRAPH.entry_node_id;})[0]||(GRAPH.nodes||[])[0]; render(s); }
  start();
})();
"""


def _esc_script(json_text: str) -> str:
    # 只转义 `<`，防止内嵌字符串里的 `</script>` 逃逸出脚本标签。
    return json_text.replace("<", "\\u003c")


def _esc_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def build_playable_html(graph: dict, title: str | None = None) -> str:
    """把 YIWA StoryGraph 编译为自包含可玩 HTML。"""
    doc_title = title or graph.get("graph_id") or "互动影视"
    graph_json = _esc_script(json.dumps(graph, ensure_ascii=False))
    return (
        "<!doctype html>\n"
        '<html lang="zh"><head><meta charset="utf-8"/>'
        '<meta name="viewport" content="width=device-width,initial-scale=1"/>'
        f"<title>{_esc_html(doc_title)}</title><style>{_CSS}</style></head>"
        f'<body><div id="wrap"><h1>{_esc_html(doc_title)}</h1><div id="if-player"></div></div>'
        f"<script>var GRAPH={graph_json};</script>"
        f"<script>{_PLAYER_JS}</script>"
        "</body></html>"
    )