"use client";

// IDE 状态 hook：集中持有剧情图 / 制品 / 轨迹 / 角色，并提供真实 API 动作。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { addEdge, useEdgesState, useNodesState, type Connection, type Edge, type Node } from "reactflow";
import type { AgentRunOut, ArtifactOut } from "@/types";
import {
  createPlaySession,
  dialogueOperation,
  getArtifactHistory,
  getStoryGraph,
  getTraces,
  listCharacters,
  listProjects,
  putStoryGraph,
  rerunTask,
  reviseArtifact,
  sceneOperation,
  type StoryGraphPayload,
} from "@/lib/api";
import { latestOf, type IdeChoice, type IdeEdge, type IdeNode } from "./workspace";

type SVar = { name: string; type: string; initial: unknown };
type Play = { session_id: string; state: Record<string, unknown>; current_node_id: string };

export function useIde({ projectId, flash }: { projectId: string; flash: (msg: string) => void }) {
  const [projName, setProjName] = useState("未命名作品");
  const [projStatus, setProjStatus] = useState("building");

  const [nodes, setNodes, onNodesChange] = useNodesState<IdeNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [entry, setEntry] = useState<string | null>(null);
  const [variables, setVariables] = useState<SVar[]>([]);
  const [graphVersion, setGraphVersion] = useState(0);

  const [artifacts, setArtifacts] = useState<ArtifactOut[]>([]);
  const [traces, setTraces] = useState<AgentRunOut[]>([]);
  const [chars, setChars] = useState<{ character_id: string; name: string; role: string }[]>([]);

  const [play, setPlay] = useState<Play | null>(null);
  const [playErr, setPlayErr] = useState("");

  const reloadArtifacts = useCallback(() => {
    if (!projectId) return;
    getArtifactHistory(projectId).then(setArtifacts).catch(() => {});
  }, [projectId]);

  const reloadTraces = useCallback(() => {
    if (!projectId) return;
    getTraces(projectId).then(setTraces).catch(() => {});
  }, [projectId]);

  const reloadChars = useCallback(() => {
    if (!projectId) return;
    listCharacters(projectId)
      .then((c) => setChars(c.map((x) => ({ character_id: x.character_id, name: x.name, role: x.role }))))
      .catch(() => {});
  }, [projectId]);

  const loadMeta = useCallback(() => {
    if (!projectId) return;
    listProjects()
      .then((ps) => {
        const p = ps.find((x) => x.id === projectId);
        if (p) { setProjName(p.title || p.goal || "未命名作品"); setProjStatus(p.status); }
      })
      .catch(() => {});
  }, [projectId]);

  const loadGraph = useCallback(() => {
    if (!projectId) return;
    getStoryGraph(projectId)
      .then((d) => {
        const g = d.graph as { graph_id: string; nodes: IdeNode[]; edges: IdeEdge[]; variables?: SVar[]; entry_node_id: string | null };
        setGraphVersion(d.version ?? 0);
        setEntry(g.entry_node_id ?? null);
        setVariables(g.variables ?? []);
        const ns: Node<IdeNode>[] = (g.nodes ?? []).map((n, i) => ({
          id: n.node_id,
          type: "ide",
          position: n.position && typeof n.position.x === "number" && typeof n.position.y === "number"
            ? { x: n.position.x, y: n.position.y }
            : { x: 50 + (i % 4) * 300, y: 90 + Math.floor(i / 4) * 240 },
          data: { ...n, isEntry: g.entry_node_id === n.node_id },
        }));
        setNodes(ns);
        const es: Edge[] = (g.edges ?? []).map((e) => ({ id: e.edge_id, source: e.source, target: e.target, label: e.label }));
        (g.nodes ?? []).forEach((n) =>
          (n.choices ?? []).forEach((c) => {
            if (c.next_node) es.push({ id: `ch-${n.node_id}-${c.choice_id}`, source: n.node_id, target: c.next_node, label: c.text });
          }),
        );
        setEdges(es);
      })
      .catch(() => flash("剧情图加载失败"));
  }, [projectId, flash, setNodes, setEdges]);

  useEffect(() => {
    if (!projectId) return;
    loadMeta();
    reloadArtifacts();
    reloadTraces();
    reloadChars();
  }, [projectId, loadMeta, reloadArtifacts, reloadTraces, reloadChars]);

  useEffect(() => {
    loadGraph();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const nodeMeta = useMemo(() => {
    const m: Record<string, { agent?: string; version?: number }> = {};
    for (const a of latestOf(artifacts)) {
      const i = a.kind.indexOf(":");
      if (i < 0) continue;
      const nid = a.kind.slice(i + 1);
      if (nid) m[nid] = { agent: a.agent, version: a.version };
    }
    return m;
  }, [artifacts]);

  const onConnect = useCallback(
    (c: Connection) => setEdges((eds) => addEdge({ ...c, id: `e-${Date.now()}` } as Edge, eds) as Edge[]),
    [setEdges],
  );

  const updateNode = useCallback(
    (id: string, patch: Partial<IdeNode>) =>
      setNodes((nds) => nds.map((n) => (n.id === id ? ({ ...n, data: { ...n.data, ...patch } as IdeNode } as Node<IdeNode>) : n))),
    [setNodes],
  );

  const addNode = useCallback(
    (kind: string) => {
      const id = `nd-${Date.now()}`;
      setNodes((nds) => [
        ...nds,
        { id, type: "ide", position: { x: 160 + Math.random() * 220, y: 160 + Math.random() * 220 }, data: { node_id: id, kind, title: "新节点", summary: "", choices: [] } as IdeNode } as Node<IdeNode>,
      ]);
    },
    [setNodes],
  );

  const deleteNode = useCallback(
    (id: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== id));
      setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
    },
    [setNodes, setEdges],
  );

  const addChoice = useCallback(
    (nodeId: string) => {
      const n = nodes.find((x) => x.id === nodeId);
      if (!n) return;
      updateNode(nodeId, { choices: [...(n.data.choices ?? []), { choice_id: `ch-${Date.now()}`, text: "新选项", next_node: null }] });
    },
    [nodes, updateNode],
  );

  const updateChoice = useCallback(
    (nodeId: string, choiceId: string, patch: Partial<IdeChoice>) => {
      setNodes((nds) =>
        nds.map((nn) =>
          nn.id === nodeId
            ? { ...nn, data: { ...nn.data, choices: (nn.data.choices ?? []).map((c) => (c.choice_id === choiceId ? { ...c, ...patch } : c)) } as IdeNode }
            : nn,
        ),
      );
    },
    [setNodes],
  );

  const deleteChoice = useCallback(
    (nodeId: string, choiceId: string) => {
      setNodes((nds) =>
        nds.map((nn) =>
          nn.id === nodeId
            ? { ...nn, data: { ...nn.data, choices: (nn.data.choices ?? []).filter((c) => c.choice_id !== choiceId) } as IdeNode }
            : nn,
        ),
      );
    },
    [setNodes],
  );

  const saveGraph = useCallback(async () => {
    if (!projectId) return;
    const graph = {
      graph_id: `story-${projectId}`,
      nodes: nodes.map((n) => ({
        node_id: n.id,
        kind: n.data.kind,
        title: n.data.title,
        summary: n.data.summary,
        choices: (n.data.choices ?? []).map((c) => c),
        position: n.position ? { x: n.position.x, y: n.position.y } : null,
        locked: n.data.locked ?? false,
      } as IdeNode)),
      edges: edges.filter((e) => !e.id.startsWith("ch-")).map((e) => ({ edge_id: e.id, source: e.source, target: e.target, label: (e.label as string) ?? "" } as IdeEdge)),
      variables: variables.filter((v) => v.name),
      entry_node_id: entry,
    };
    try {
      const d = await putStoryGraph(projectId, graph as StoryGraphPayload, "IDE 画布编辑");
      setGraphVersion(d.version ?? graphVersion);
      flash("已保存");
      reloadTraces();
    } catch {
      flash("保存失败");
    }
  }, [projectId, nodes, edges, variables, entry, graphVersion, flash, reloadTraces]);

  const aiModify = useCallback(
    async (nodeId: string, instr: string): Promise<{ ok: boolean; msg: string }> => {
      if (!instr.trim()) return { ok: false, msg: "请输入修改要求" };
      const n = nodes.find((x) => x.id === nodeId);
      const kind = n?.data?.kind ?? "scene";
      try {
        if (kind === "scene") {
          await sceneOperation(projectId, "revise", nodeId, instr);
        } else if (kind === "dialogue") {
          await dialogueOperation(projectId, "revise", nodeId, null, instr);
        } else {
          await reviseArtifact(projectId, "story_graph", instr);
        }
        reloadArtifacts();
        loadGraph();
        return { ok: true, msg: "多 Agent 修改完成（已生成新版本）" };
      } catch (e) {
        return { ok: false, msg: `修改失败：${String((e as Error).message ?? e)}` };
      }
    },
    [projectId, nodes, reloadArtifacts, loadGraph],
  );

  const rerunSelected = useCallback(
    async (nodeId: string) => {
      const art = latestOf(artifacts).find((a) => a.kind.includes(`:${nodeId}`));
      if (!art) return flash("该节点无独立任务");
      try {
        await rerunTask(projectId, art.task_id);
        flash("已触发重新生成");
        reloadTraces();
      } catch (e) {
        flash(`失败：${String((e as Error).message)}`);
      }
    },
    [projectId, artifacts, flash, reloadTraces],
  );

  const playProject = useCallback(() => {
    if (!projectId) return;
    setPlayErr("");
    createPlaySession(projectId)
      .then((s) => setPlay({ session_id: s.session_id, state: s.state ?? {}, current_node_id: s.current_node_id ?? "" }))
      .catch((e) => setPlayErr(String((e as Error).message ?? e)));
  }, [projectId]);

  return {
    projName, projStatus,
    nodes, edges, onNodesChange, onEdgesChange, onConnect, setEdges,
    entry, setEntry, variables, setVariables, graphVersion,
    artifacts, traces, chars, nodeMeta,
    play, playErr,
    reloadArtifacts, reloadTraces, reloadChars, loadGraph,
    updateNode, deleteNode, addNode, addChoice, updateChoice, deleteChoice, saveGraph, aiModify, rerunSelected, playProject,
  };
}