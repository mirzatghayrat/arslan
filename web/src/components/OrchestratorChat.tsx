import React, { useState, useRef, useEffect } from 'react';
import { 
  ArrowRight, Sparkles, Terminal, Wrench, BookOpen, 
  AlertTriangle, CheckCircle2, XOctagon, Clock, Play, 
  Layers, Lock, PlayCircle, Eye, EyeOff, User, CornerDownRight,
  RefreshCcw, Info, Cpu, X, Send, ChevronRight, Activity, Plus,
  Search, Globe, ChevronDown, ChevronUp, Database
} from 'lucide-react';
import { Message, Spawn, Tool, Skill } from '../types';
import { TOOLS, SKILLS } from '../data';
import SFSymbol from './SFSymbol';

interface OrchestratorChatProps {
  chatHistory: Message[];
  setChatHistory: React.Dispatch<React.SetStateAction<Message[]>>;
  spawns: Spawn[];
  currentStyle: 'quartz' | 'brutalist' | 'linear';
  setCurrentStyle: (style: 'quartz' | 'brutalist' | 'linear') => void;
  activeThread: any;
}

export default function OrchestratorChat({
  chatHistory,
  setChatHistory,
  spawns,
  currentStyle,
  setCurrentStyle,
  activeThread
}: OrchestratorChatProps) {
  const [inputValue, setInputValue] = useState('');
  const [isSimulating, setIsSimulating] = useState(false);
  const [simulationStep, setSimulationStep] = useState(0);
  const [collapsedToolActivities, setCollapsedToolActivities] = useState<Record<string, boolean>>({});
  
  // Custom states for Spawns Pipeline Dock & Split-Screen Co-pilot Sandbox
  const [spawnStatuses, setSpawnStatuses] = useState<Record<string, 'idle' | 'working' | 'review_pending'>>({});
  const [selectedAssignSpawnId, setSelectedAssignSpawnId] = useState<string | null>(null);
  const [assignTaskText, setAssignTaskText] = useState('');

  const [splitSpawnId, setSplitSpawnId] = useState<string | null>(null);
  const [subInputValue, setSubInputValue] = useState('');
  const [subChats, setSubChats] = useState<Record<string, Message[]>>({});
  const [subDrafts, setSubDrafts] = useState<Record<string, string>>({});
  const [subTyping, setSubTyping] = useState<boolean>(false);

  // Global Integration Discovery & Repository Engine States
  const [showSandboxSearch, setShowSandboxSearch] = useState(true); // Keep open initially for discoverability
  const [integrationQuery, setIntegrationQuery] = useState('');
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [mcpRegistry, setMcpRegistry] = useState<{name: string, url: string, description: string, tags: string[]}[]>([
    {
      name: 'Brave Search Core',
      url: 'https://github.com/brave/brave-mcp-server',
      description: 'Secure, local proxy-bypassing web crawler and semantic text extractor API node.',
      tags: ['MCP', 'Web Crawler']
    },
    {
      name: 'Local SQLite Analyzer',
      url: 'https://github.com/mcp-community/sqlite-mcp-server',
      description: 'Executes high-performance sqlite sandbox trace queries and schemas lookup.',
      tags: ['MCP', 'Database']
    }
  ]);
  const [skillRegistry, setSkillRegistry] = useState<{name: string, repo: string, capabilities: string[]}[]>([
    {
      name: 'Penetration Auditing',
      repo: 'https://github.com/test-security/network-auditor',
      capabilities: ['Intrusion Trace Audit', 'Port Handshake Map', 'Local Network Sniffing']
    }
  ]);
  const [evaluationResult, setEvaluationResult] = useState<{
    url: string;
    name: string;
    summary: string;
    capabilities: string[];
    moat: string;
    bestUse: string;
    type: 'MCP' | 'Skill';
  } | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const subBottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  useEffect(() => {
    if (splitSpawnId) {
      subBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [subChats, splitSpawnId, subTyping]);

  const handleEvaluateRepository = (urlOrQuery: string) => {
    if (!urlOrQuery.trim()) return;
    setIsEvaluating(true);
    setEvaluationResult(null);

    // Normalize input
    const query = urlOrQuery.toLowerCase().trim();

    setTimeout(() => {
      let resultName = 'Custom Agent Workspace Spec';
      let resultUrl = urlOrQuery;
      let summary = 'Custom third-party integration analyzed via Sandboxed Engine. Perfect configuration matching found.';
      let capabilities = [
        'Automatic entry point injection',
        'Payload compliance checking',
        'Secured prompt routing schema'
      ];
      let moat = 'Dynamic authentication virtualization prevents API token leakages post-compilation.';
      let bestUse = 'Ideal for equipping general Spawns with custom task runner protocols.';
      let evaluatedType: 'MCP' | 'Skill' = 'MCP';

      if (query.includes('gdrive') || query.includes('google drive') || query.includes('google-drive') || query.includes('workspace')) {
        resultName = 'Google Drive Workspace Core';
        resultUrl = 'https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive';
        summary = 'Allows direct OAuth workspace document reads, deep hierarchical folder searches, and live-stream ingestion in Google Workspace formats.';
        capabilities = [
          'Workspace doc metadata sync & search indexing',
          'Incremental chunk-by-chunk Sheet reader',
          'Granular OAuth security access scopes validator'
        ];
        moat = 'Granular read-only token restriction layer, blocking server-side prompt injection attacks from overriding active live documents.';
        bestUse = 'Enables Arslan Core to extract spreadsheet records and draft immediate automated briefs dynamically.';
        evaluatedType = 'MCP';
      } else if (query.includes('git') || query.includes('github')) {
        resultName = 'Git Workspace Controller';
        resultUrl = 'https://github.com/mcp-community/git-mcp';
        summary = 'Provides repository commit tree trace, atomic diff visualization, and auto-refactoring branches checkout tools directly within sandboxed workspace paths.';
        capabilities = [
          'Diff tree tracer with structural markdown preview',
          'Branch auto-protection rules lock',
          'Safe staged files cataloger with rollback memory'
        ];
        moat = 'Isolated file-system sandbox tracing, fully shielding the parent active operating system context from malicious checkout scripts.';
        bestUse = 'Enables Huan/Hatchery sub-agents to draft layout revisions and write commits post-evaluation.';
        evaluatedType = 'MCP';
      } else if (query.includes('brave') || query.includes('search') || query.includes('crawler') || query.includes('browser')) {
        resultName = 'Brave Search Intelligence Node';
        resultUrl = 'https://github.com/brave/brave-mcp-server';
        summary = 'A specialized web query engine optimized for agents, providing secure high-performance web crawls and selector-based text extraction.';
        capabilities = [
          'Auto-bypassing bot-detection web index fetcher',
          'Semantic HTML main text stripper layer',
          'Localized news variance trend aggregator'
        ];
        moat = 'Advanced rate-limit handling and residential proxy rotating built-built to secure uninterrupted indexing.';
        bestUse = 'Equips Aletheia with live financial news indexes across global web indices instantly.';
        evaluatedType = 'MCP';
      } else if (query.includes('milvus') || query.includes('vector') || query.includes('rag')) {
        resultName = 'Milvus Vector-Cache Connector';
        resultUrl = 'https://github.com/milvus-io/milvus-mcp-server';
        summary = 'A high-dimensional collection indexing node for storing long-term memory semantic layers securely and tracing cosine similarity vectors.';
        capabilities = [
          'Dynamic schema creator & metadata collection mapper',
          'Cosine similarity metric trace lookups',
          'RAG context payload optimizer'
        ];
        moat = 'Native cluster connection cache pools, reducing round-trip vector lookup hop latencies to less than 15ms.';
        bestUse = 'Enables Arslan Memory registers to store deep historic logs in fully searchable vector slots.';
        evaluatedType = 'MCP';
      } else if (query.includes('postgres') || query.includes('sql') || query.includes('mysql') || query.includes('database')) {
        resultName = 'Relational DB Smart Analyzer';
        resultUrl = urlOrQuery.startsWith('http') ? urlOrQuery : 'https://github.com/mcp-community/postgres-server';
        summary = 'Exposes database structure introspection, automated schema indexing, and analytical SQL tracer tools with secure execution limits.';
        capabilities = [
          'Automatic foreign-key trace mapper',
          'Bounded analytical DML analyzer & schema checker',
          'Transaction safety dry-run layer'
        ];
        moat = 'Active query limit capping and injection regex filtering, enabling safe read-only SQL generation for autonomous agents.';
        bestUse = 'Enables background spawns to perform automated statistics aggregation on dynamic database clusters.';
        evaluatedType = 'MCP';
      } else {
        // Dynamic fallback generating based on input path
        let extractedName = 'Custom Repository Integration';
        const parts = query.replace('https://', '').replace('github.com/', '').split('/');
        if (parts.length > 1) {
          extractedName = parts[parts.length - 1].split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
        } else if (urlOrQuery) {
          extractedName = urlOrQuery.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
        }
        
        resultName = `${extractedName} Core`;
        summary = `A verified ${extractedName} capability module analyzed on-chain. Fully compatible with Arslan dual-plane orchestration constraints.`;
        capabilities = [
          `Introspective ${extractedName} API communication connector`,
          `Dynamic payload wrapper with schema-level validation`,
          `High-throughput error handling diagnostic protocol`
        ];
        moat = `Strict sandbox encapsulation blocks execution of arbitrary runtime buffers to shield the workspace.`;
        bestUse = `Enables Arslan Core to register ${extractedName} as an active specialty node on-demand.`;
        evaluatedType = query.includes('mcp') || query.includes('server') ? 'MCP' : 'Skill';
      }

      setEvaluationResult({
        url: resultUrl,
        name: resultName,
        summary,
        capabilities,
        moat,
        bestUse,
        type: evaluatedType
      });
      setIsEvaluating(false);
    }, 900);
  };

  const handleAddToMCP = () => {
    if (!evaluationResult) return;
    
    // Check if already exists in list
    if (mcpRegistry.some(m => m.name === evaluationResult.name)) {
      return;
    }

    setMcpRegistry(prev => [
      ...prev,
      {
        name: evaluationResult.name,
        url: evaluationResult.url,
        description: evaluationResult.summary,
        tags: ['MCP', 'User Added']
      }
    ]);

    // Send brief confirmation chat notification from Arslan
    const mcpMsg: Message = {
      id: `mcp-add-${Date.now()}`,
      sender: 'arslan',
      senderName: 'Arslan Core',
      senderAvatar: '🦁',
      text: `📥 **MCP Registry Updated:** Successfully registered **[${evaluationResult.name}]** into the active sandbox tool container pool. It is now standard authorized (🔓) for all sub-spawns.`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    setChatHistory(prev => [...prev, mcpMsg]);
  };

  const handleAddToSkill = () => {
    if (!evaluationResult) return;

    if (skillRegistry.some(s => s.name === evaluationResult.name)) {
      return;
    }

    setSkillRegistry(prev => [
      ...prev,
      {
        name: evaluationResult.name,
        repo: evaluationResult.url,
        capabilities: evaluationResult.capabilities
      }
    ]);

    const skillMsg: Message = {
      id: `skill-add-${Date.now()}`,
      sender: 'arslan',
      senderName: 'Arslan Core',
      senderAvatar: '🦁',
      text: `🛡️ **Capabilities Ledger Expanded:** Added Skillset **[${evaluationResult.name}]** to special specialized skill registers. Spawns can now inherit its specific trace permissions.`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    setChatHistory(prev => [...prev, skillMsg]);
  };

  const handleSynthesizeSpawn = () => {
    if (!evaluationResult) return;

    // Simulate synthesis notification inside chat history
    const synthUserMsg: Message = {
      id: `synth-user-${Date.now()}`,
      sender: 'user',
      senderName: 'Mirzat',
      senderAvatar: '🦁',
      text: `🔄 **Initiate Autonomous Spawn Synthesis:** Constructing new sub-specialist agent equipped with capability: **[${evaluationResult.name}]**.`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    const synthMsg: Message = {
      id: `synth-act-${Date.now()}`,
      sender: 'arslan',
      senderName: 'Arslan Core',
      senderAvatar: '🦁',
      text: `✨ **Arslan Multi-Agent Gateway Integrated:** Custom specialist branch successfully synthesized!\n\n**Specialist Agent Name:** ${evaluationResult.name === 'Custom Repository Integration Core' ? 'Arbitrage' : evaluationResult.name.split(' ')[0]} Bot\n**Status:** Fully Calibrated (Ready)\n**Equipped Skill:** ${evaluationResult.name}\n**Active Hooks:** Connected to tool endpoint *${evaluationResult.url}*.\n\nReady to aggregate high-fidelity telemetry post-execution.`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      spawnIntro: {
        name: `${evaluationResult.name === 'Custom Repository Integration Core' ? 'Arbitrage' : evaluationResult.name.split(' ')[0]} Specialist`,
        avatarEmoji: '⚡',
        domain: `Integration Node: ${evaluationResult.name}`,
        tools: ['web-evaluator'],
        skills: ['autonomous_synthesis']
      }
    };

    setChatHistory(prev => [...prev, synthUserMsg]);
    
    // Stagger Arslan response
    setTimeout(() => {
      setChatHistory(prev => [...prev, synthMsg]);
    }, 600);
  };

  const handleLaunchSpawnTask = (spawnId: string, customTask?: string) => {
    const spawn = spawns.find(s => s.id === spawnId);
    if (!spawn) return;

    setSelectedAssignSpawnId(null);
    const taskText = customTask?.trim() || `Conduct automatic Q1 domain studies and compile structural briefs.`;
    setAssignTaskText('');

    // Pre-set status to working
    setSpawnStatuses(prev => ({ ...prev, [spawnId]: 'working' }));

    // Append trigger notification to primary feed
    const triggerMsg: Message = {
      id: `trigger-msg-${Date.now()}`,
      sender: 'user',
      senderName: 'Mirzat',
      senderAvatar: '🦁',
      text: `⚡ **Operator delegated sub-task to [${spawn.name}]:**\n"${taskText}"`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    setChatHistory(prev => [...prev, triggerMsg]);

    // Stage 1: Active processing note (1.2s later)
    setTimeout(() => {
      const liveMsg: Message = {
        id: `live-proc-${Date.now()}`,
        sender: 'arslan',
        senderName: 'Arslan Core',
        senderAvatar: '🦁',
        text: `⚙️ **Local Sandboxed Container Spawned:** Spawning active virtualization socket for **${spawn.name}**. Mounting credentials & local tools...`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setChatHistory(prev => [...prev, liveMsg]);
    }, 1200);

    // Stage 2: Spawn initiates Tools Activity (2.6s later)
    setTimeout(() => {
      const toolMsg: Message = {
        id: `tool-act-${Date.now()}`,
        sender: 'spawn',
        senderName: spawn.name,
        senderAvatar: spawn.avatarEmoji,
        text: `Initializing automatic index compilation relative to input parameters...`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        toolActivity: {
          id: `sand-tool-${Date.now()}`,
          toolName: spawn.id === 'spawn-aletheia' ? 'Financial Index Parser' : 'XiaoHongShu Caption Engine',
          emoji: spawn.id === 'spawn-aletheia' ? '📈' : '✍️',
          status: 'completed',
          action: `Scraping context coordinates for target request: "${taskText}"`,
          outputSummary: spawn.id === 'spawn-aletheia' 
            ? 'Parsed 14 consensus forecasts. Adjusted Blackwell pipeline weight coefficients.' 
            : 'Generated 3 copywriting slogan hooks with localized high-click engagement markers.',
          collapsed: false
        }
      };
      setChatHistory(prev => [...prev, toolMsg]);
    }, 2600);

    // Stage 3: Completion & Review Trigger (5.0s later)
    setTimeout(() => {
      setSpawnStatuses(prev => ({ ...prev, [spawnId]: 'review_pending' }));

      // Setup initial Sandbox Chat & Draft and stores it
      const defaultDraftText = spawn.id === 'spawn-aletheia' 
        ? `### 📊 NVIDIA Q1 FINANCIAL SYNTHESIS REPORT\n\n- **Consensus Outlook:** High bullish conviction. Blackwell demand remains robust with mass production scheduled for Q4 in leading hyperscaler clusters.\n- **Variance analysis:** Revenue hit **$26.04 Billion** (+262% Year-on-year increase).\n- **Guidance Rating:** Adjusted forward trading index to outperform, establishing target price: **$1,400/share**.\n\n*Draft produced securely on Arslan isolated memory storage.*`
        : spawn.id === 'spawn-huan'
        ? `### 🚀 炸裂！英伟达Q1狂揽260亿！？ Blackwell显卡到底有多狂暴！？\n\n小红书的宝子们！今天来聊聊震撼科技圈的超级大新闻：Nvidia一季度财务业绩直接击碎华尔街天花板！\n\n- 💥 **收入狂飙 262%：** 这已经不是起飞，这是直接肉身破音速！\n- 📈 **Blackwell年底量产：** 准备好接下这波滔天算力了吗？\n\n#显卡 #英伟达 #计算美学 #硬核科技分享 #搞钱女孩必看`
        : `### ⚙️ SPECIALIST ISOLATED PIPELINE ARTIFACT\n\n- **Specialist Name:** ${spawn.name}\n- **Assigned Domain:** ${spawn.domain}\n- **Task Handled:** "${taskText}"\n\n- **Standard Findings:** Analysis verified that all model indicators match expectations. Memory slots synchronized cleanly on local loop.`;

      // Define subChat history
      const initialSubChats: Message[] = [
        {
          id: `subchat-init-${Date.now()}`,
          sender: 'spawn',
          senderName: spawn.name,
          senderAvatar: spawn.avatarEmoji,
          text: `👋 Greetings operator! I have executed the background calculation for *"${taskText}"* and deposited the results below. \n\nFeel free to provide feedback in the sub-chatter input box to refine this draft, or click **"✓ Confirm & Merge Outcome"** to push the final artifact directly into the main thread!`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ];

      setSubChats(prev => ({ ...prev, [spawnId]: initialSubChats }));
      setSubDrafts(prev => ({ ...prev, [spawnId]: defaultDraftText }));

      // Append finish notice to primary conversation
      const completeMsg: Message = {
        id: `done-proc-${Date.now()}`,
        sender: 'arslan',
        senderName: 'Arslan Core',
        senderAvatar: '🦁',
        text: `✨ **Subprocess Finalized:** Specialist **${spawn.name}** has completed generating a draft deliverables card!\n\n🔔 **Action Required:** The visual button for **"${spawn.name}"** in your **Spawns Pipeline Dock** is now glowing! Click **"👁️ Open Sandbox"** to review, adjust, and merge their work.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setChatHistory(prev => [...prev, completeMsg]);

    }, 5000);
  };

  const handleSendSubMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!subInputValue.trim() || !splitSpawnId) return;

    const spawn = spawns.find(s => s.id === splitSpawnId);
    if (!spawn) return;

    const userText = subInputValue;
    setSubInputValue('');

    const newSubMsg: Message = {
      id: `sub-msg-user-${Date.now()}`,
      sender: 'user',
      senderName: 'Mirzat',
      senderAvatar: '🦁',
      text: userText,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setSubChats(prev => ({
      ...prev,
      [splitSpawnId]: [...(prev[splitSpawnId] || []), newSubMsg]
    }));

    setSubTyping(true);
    setTimeout(() => {
      setSubTyping(false);

      const originalDraft = subDrafts[splitSpawnId] || '';
      let refinedDraft = originalDraft;

      if (userText.toLowerCase().includes('short') || userText.includes('简短') || userText.includes('缩短')) {
        refinedDraft = refinedDraft.split('\n\n').slice(0, 2).join('\n\n') + `\n\n*(Draft shortened based on operator instructions!)*`;
      } else if (userText.toLowerCase().includes('hash') || userText.includes('标签') || userText.includes('tag')) {
        refinedDraft += `\n\n#AGIAgent #SpecialistsPipeline #ArslanOrchestrator #AIStudio`;
      } else if (userText.toLowerCase().includes('title') || userText.includes('标题')) {
        refinedDraft = `👑 **REFINED AESTHETIC EXECUTIVE PREVIEW** 👑\n\n` + refinedDraft;
      } else if (userText.toLowerCase().includes('emoji') || userText.includes('表情')) {
        refinedDraft = refinedDraft.replace(/-/g, '✨ -');
      } else {
        refinedDraft += `\n\n*Update (calibrated based on instruction: "${userText}"): Draft refined with extra precision details.*`;
      }

      setSubDrafts(prev => ({ ...prev, [splitSpawnId]: refinedDraft }));

      const spawnFeedbackMsg: Message = {
        id: `sub-msg-refine-${Date.now()}`,
        sender: 'spawn',
        senderName: spawn.name,
        senderAvatar: spawn.avatarEmoji,
        text: `Understood! I've calibrated the working buffer memory accordingly based on your guidance: *"${userText}"*. Let's check out the updated draft in the editor view! ✨`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };

      setSubChats(prev => ({
        ...prev,
        [splitSpawnId]: [...(prev[splitSpawnId] || []), spawnFeedbackMsg]
      }));

    }, 800);
  };

  const handleConfirmMergeDraft = (spawnId: string) => {
    const spawn = spawns.find(s => s.id === spawnId);
    if (!spawn) return;

    const mergedDraft = subDrafts[spawnId] || '';

    const mergeMsg: Message = {
      id: `merge-msg-${Date.now()}`,
      sender: 'spawn',
      senderName: spawn.name,
      senderAvatar: spawn.avatarEmoji,
      text: `✅ **Isolated Sandbox Deliverables Confirmed & Merged to Core Thread:**\n\n${mergedDraft}\n\n*Output approved and finalized by operator.*`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setChatHistory(prev => [...prev, mergeMsg]);
    setSpawnStatuses(prev => ({ ...prev, [spawnId]: 'idle' }));
    setSplitSpawnId(null);
  };

  const handleDiscardSubSession = (spawnId: string) => {
    setSpawnStatuses(prev => ({ ...prev, [spawnId]: 'idle' }));
    setSplitSpawnId(null);
  };

  const toggleToolCollapse = (id: string) => {
    setCollapsedToolActivities(prev => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim()) return;

    const userMsg: Message = {
      id: `msg-user-${Date.now()}`,
      sender: 'user',
      senderName: 'Mirzat',
      senderAvatar: '🦁',
      text: inputValue,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setChatHistory(prev => [...prev, userMsg]);
    setInputValue('');

    // Trigger a default auto-orchestration response simulation after a short delay
    setTimeout(() => {
      const arslanThinkingMsg: Message = {
        id: `msg-arslan-${Date.now()}`,
        sender: 'arslan',
        senderName: 'Arslan',
        senderAvatar: '🦁',
        text: `Determined processing sequence for: "${userMsg.text}". Let's spin up **Aletheia** to inspect research databases and summarize this query. Spawning agent...`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        routedTo: {
          spawnId: 'spawn-aletheia',
          spawnName: 'Aletheia'
        }
      };
      setChatHistory(prev => [...prev, arslanThinkingMsg]);

      setTimeout(() => {
        const spawnIntroMsg: Message = {
          id: `msg-aletheia-intro-${Date.now()}`,
          sender: 'spawn',
          senderName: 'Aletheia',
          senderAvatar: '🦊',
          text: `Aletheia initializing. Equipped with quantitative intelligence suite. Scanning records and compiling web data now.`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          spawnIntro: {
            name: 'Aletheia',
            domain: 'Financial Market Intelligence',
            avatarEmoji: '🦊',
            tools: ['web-search', 'stock-data'],
            skills: ['financial-res']
          }
        };
        setChatHistory(prev => [...prev, spawnIntroMsg]);

        setTimeout(() => {
          const toolActMsg: Message = {
            id: `msg-tool-active-${Date.now()}`,
            sender: 'spawn',
            senderName: 'Aletheia',
            senderAvatar: '🦊',
            text: `Gathering indicators via web integration.`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            toolActivity: {
              id: `tool-${Date.now()}`,
              toolName: 'Web Search',
              emoji: '🔍',
              status: 'completed',
              action: `Searching Google & arxiv indexes for "${userMsg.text}"`,
              outputSummary: 'Extracted 4 high-integrity references. Formulating intelligence synthesis briefing.',
              collapsed: false
            }
          };
          setChatHistory(prev => [...prev, toolActMsg]);

          setTimeout(() => {
            const finalSpawnMsg: Message = {
              id: `msg-final-${Date.now()}`,
              sender: 'spawn',
              senderName: 'Aletheia',
              senderAvatar: '🦊',
              text: `Here is my synthesized findings summary based on Tavily index search. It appears that the recent parameters are consistent with general market indicators. Let me know if you would like me to conduct a mathematical plot model!`,
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            };
            setChatHistory(prev => [...prev, finalSpawnMsg]);
          }, 1200);
        }, 1200);
      }, 1200);
    }, 1000);
  };

  const triggerPresetScenario = (type: 'nv' | 'sec') => {
    setIsSimulating(true);
    setChatHistory([]);

    if (type === 'nv') {
      // Nvidia stock simulation
      const steps: (() => void)[] = [
        () => setChatHistory([
          {
            id: 'n-1',
            sender: 'user',
            senderName: 'Mirzat',
            senderAvatar: '🦁',
            text: 'Compile Q1 Nvidia financial results and generate a viral graphic slide highlighting top takeaways.',
            timestamp: '12:00'
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 'n-2',
            sender: 'arslan',
            senderName: 'Arslan',
            senderAvatar: '🦁',
            text: 'Task interpreted. Parsing model instructions. Spawner activated: delegate analytical modeling to **Aletheia** and creative assets to **Huan**. Starting sequence...',
            timestamp: '12:00',
            routedTo: { spawnId: 'spawn-aletheia', spawnName: 'Aletheia' }
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 'n-3',
            sender: 'spawn',
            senderName: 'Aletheia',
            senderAvatar: '🦊',
            text: 'Let’s pull raw data-point inputs. Reviewing tools.',
            timestamp: '12:01',
            spawnIntro: {
              name: 'Aletheia',
              domain: 'Financial Market Intelligence',
              avatarEmoji: '🦊',
              tools: ['stock-data', 'py-exec'],
              skills: ['financial-res', 'stat-analysis']
            }
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 'n-4',
            sender: 'spawn',
            senderName: 'Aletheia',
            senderAvatar: '🦊',
            text: 'Polling standard ticker stocks for valuation matrices.',
            timestamp: '12:01',
            toolActivity: {
              id: 'nt-1',
              toolName: 'Stock Sandbox',
              emoji: '📈',
              status: 'completed',
              action: 'Initializing tick parser for trading data: $NVDA',
              outputSummary: 'Revenue: $26.04B (+262% YoY). EPS: $6.12 beat Wall Street consensus by 9.3%.',
              collapsed: false
            }
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 'n-5',
            sender: 'spawn',
            senderName: 'Aletheia',
            senderAvatar: '🦊',
            text: 'Quantitative study completed. NVDA figures outpaced general market limits. Forward guidance exceeds previous ceilings. Forwarding indices to Huan for visual slide creation.',
            timestamp: '12:02'
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 'n-6',
            sender: 'arslan',
            senderName: 'Arslan',
            senderAvatar: '🦁',
            text: 'Aletheia analytics accepted. Routing structured text models to **Huan** (RED Agent) for aesthetic visual transformation.',
            timestamp: '12:02',
            routedTo: { spawnId: 'spawn-huan', spawnName: 'Huan' }
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 'n-7',
            sender: 'spawn',
            senderName: 'Huan',
            senderAvatar: '🐱',
            text: 'Huan booted. Ready to translate complex math sheet into viral creative slides.',
            timestamp: '12:02',
            spawnIntro: {
              name: 'Huan',
              domain: 'RED / XiaoHongShu Copywriting',
              avatarEmoji: '🐱',
              tools: ['canvas-render', 'web-search'],
              skills: ['seo-opt', 'infographic-design']
            }
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 'n-8',
            sender: 'spawn',
            senderName: 'Huan',
            senderAvatar: '🐱',
            text: 'Rendering layout card with orange styling...',
            timestamp: '12:03',
            toolActivity: {
              id: 'nt-2',
              toolName: 'SVGRenderer',
              emoji: '🎨',
              status: 'completed',
              action: 'Generating rich dark card: 1080x1350px viewport with glowing orange border highlights',
              outputSummary: 'Compiled custom SVG image detailing post-market parameters.',
              collapsed: false
            }
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 'n-9',
            sender: 'spawn',
            senderName: 'Huan',
            senderAvatar: '🐱',
            text: 'Here is the draft slide and copy! Let’s publish! \n\n🚀 **NVIDIA BEATS: $26B Blackwell Surge!** \n- Revenue +262% YoY!\n- Blackwell mass production scheduled Q4',
            timestamp: '12:03'
          }
        ])
      ];

      execSteps(steps);
    } else {
      // Escalation Scenario
      const steps: (() => void)[] = [
        () => setChatHistory([
          {
            id: 's-1',
            sender: 'user',
            senderName: 'Mirzat',
            senderAvatar: '🦁',
            text: 'Aletheia, please test our internal local network address (10.0.0.15) for open ports to ensure security.',
            timestamp: '14:20'
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 's-2',
            sender: 'arslan',
            senderName: 'Arslan',
            senderAvatar: '🦁',
            text: 'Routing task to **Aletheia**. Standard security clearance audit in progress.',
            timestamp: '14:20',
            routedTo: { spawnId: 'spawn-aletheia', spawnName: 'Aletheia' }
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 's-3',
            sender: 'spawn',
            senderName: 'Aletheia',
            senderAvatar: '🦊',
            text: 'Understood. Validating my assigned toolset capabilities.',
            timestamp: '14:21',
            spawnIntro: {
              name: 'Aletheia',
              domain: 'Financial Market Intelligence',
              avatarEmoji: '🦊',
              tools: ['web-search', 'stock-data'],
              skills: ['financial-res']
            }
          }
        ]),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 's-4',
            sender: 'spawn',
            senderName: 'Aletheia',
            senderAvatar: '🦊',
            text: 'I detect that the execution of an intrusive local network port scan requires "Network Penetration Auditing" skill which is standard locked (🔒) on this spawn instance. Initiating Escalation Request to Arslan...',
            timestamp: '14:21',
            escalation: {
              id: 'esc-1',
              spawnName: 'Aletheia',
              issue: 'Requested port-scan action requires elevated Network Penetration Auditing equipment',
              status: 'need_raised'
            }
          }
        ]),
        () => setChatHistory(prev => {
          return prev.map(m => {
            if (m.id === 's-4' && m.escalation) {
              return {
                ...m,
                escalation: { ...m.escalation, status: 'arslan_resolving' }
              };
            }
            return m;
          });
        }),
        () => setChatHistory(prev => {
          return prev.map(m => {
            if (m.id === 's-4' && m.escalation) {
              return {
                ...m,
                escalation: { 
                  ...m.escalation, 
                  status: 'refused',
                  resolutionMessage: 'Escalation Denied: Network Penetration Auditing is a Tier-3 restrictive weapon tool. Self-hosted instances are prohibited from mounting host sockets without developer credential flags. Execution halted.' 
                }
              };
            }
            return m;
          });
        }),
        () => setChatHistory(prev => [
          ...prev,
          {
            id: 's-7',
            sender: 'arslan',
            senderName: 'Arslan',
            senderAvatar: '🦁',
            text: 'Escalation safety audit concluded. The request was **Refused**. Spawns are sandboxed from external active probing to enforce strict security boundaries. Let me know if you would like to run standard analytic charts instead!',
            timestamp: '14:22'
          }
        ])
      ];

      execSteps(steps);
    }
  };

  const execSteps = (steps: (() => void)[]) => {
    let index = 0;
    const executeNext = () => {
      if (index < steps.length) {
        steps[index]();
        setSimulationStep(index + 1);
        index++;
        setTimeout(executeNext, 1100);
      } else {
        setIsSimulating(false);
      }
    };
    executeNext();
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#0d0f15] relative overflow-hidden">
      {/* Absolute Ambient Background Lights for Quartz Theme */}
      {currentStyle === 'quartz' && (
        <>
          <div className="absolute top-1/4 left-1/3 w-[30rem] h-[30rem] bg-[#FF8E24]/5 blur-[120px] rounded-full pointer-events-none -translate-x-1/2 -translate-y-1/2"></div>
          <div className="absolute bottom-1/4 right-0 w-[40rem] h-[40rem] bg-amber-600/[0.03] blur-[150px] rounded-full pointer-events-none translate-x-1/3 translate-y-1/3"></div>
        </>
      )}



      {/* Simulator Interactive Control Strip & Spawns Docket Integrated */}
      <div className="bg-[#121622]/60 border-b border-[#1e2330]/80 px-6 py-2.5 flex flex-row items-center justify-between gap-4 select-none text-[11px] z-10">
        <div className="flex items-center gap-2 shrink-0">
          <Terminal className="w-4 h-4 text-amber-500" />
          <span className="text-gray-300 font-mono font-bold uppercase tracking-wider">Interactive Spawner Sandbox:</span>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {(() => {
            const currentThreadMembers = activeThread?.memberSpawnIds || [];
            const memberSpawns = spawns.filter(s => currentThreadMembers.includes(s.id));
            
            // Fallback: if no members assigned yet, show active sandbox targets Aletheia & Huan
            const activeDisplayList = memberSpawns.length > 0 ? memberSpawns : spawns.slice(0, 2);

            return activeDisplayList.map(spawn => {
              const status = spawnStatuses[spawn.id] || 'idle';
              const isWorking = status === 'working';
              const isReviewPending = status === 'review_pending';
              const isSplitActive = splitSpawnId === spawn.id;

              // Determine status indicator animation to place in front of spawn name
              let statusIndicator = null;
              if (isWorking) {
                // Active running indicator
                statusIndicator = (
                  <span className="relative flex h-2 w-2 mr-1">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
                  </span>
                );
              } else if (isReviewPending) {
                // High-energy blinking alert indicator requesting action
                statusIndicator = (
                  <span className="relative flex h-2 w-2 mr-1">
                    <span className="animate-pulse absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-80 scale-125"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-rose-500 animate-ping"></span>
                  </span>
                );
              } else {
                // Normal quiet breathing green indicator for ready/idle
                statusIndicator = (
                  <span className="relative flex h-1.5 w-1.5 mr-1">
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500/80"></span>
                  </span>
                );
              }

              return (
                <button
                  key={spawn.id}
                  onClick={() => {
                    if (splitSpawnId === spawn.id) {
                      setSplitSpawnId(null);
                    } else {
                      setSplitSpawnId(spawn.id);
                      if (status === 'idle') {
                        handleLaunchSpawnTask(spawn.id);
                      }
                    }
                  }}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all text-xs font-semibold select-none cursor-pointer ${
                    isReviewPending 
                      ? 'border-rose-500/60 bg-rose-950/15 text-rose-300 hover:border-rose-400 shadow-md shadow-rose-500/5 animate-pulse' 
                      : isWorking
                      ? 'border-amber-500/30 bg-amber-500/5 text-amber-500/80 hover:border-amber-500/60'
                      : isSplitActive
                      ? 'border-[#FF8E24] bg-[#FF8E24]/10 text-[#FF8E24]'
                      : 'border-[#1e2330] bg-[#121622]/40 hover:border-[#3a4460] text-gray-300 hover:text-white'
                  }`}
                  title={
                    isReviewPending 
                      ? 'Action Required - Click to confirm or adjust work' 
                      : isWorking 
                      ? `${spawn.name} is working... Click to view live buffer` 
                      : `Click to toggle split-dialog and trigger ${spawn.name}`
                  }
                >
                  {statusIndicator}
                  <span>{spawn.name}</span>
                </button>
              );
            });
          })()}
        </div>
      </div>

      {/* Global Integration Discovery & Repository Engine (Tool-Hub) has been successfully relocated to the Spawns Ledger screen directly above the Spawns list card grid. */}

      {/* Main Container: Split-screen dual workframes if splitSpawnId is assigned */}
      <div className="flex-1 flex overflow-hidden relative">
        <div className={`flex-1 flex flex-col h-full overflow-hidden transition-all duration-300 relative ${
          splitSpawnId ? 'w-[55%] border-r border-[#1e2330]' : 'w-full'
        }`}>
          {/* Scrollable Chat Area */}
          <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {chatHistory.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-2xl mx-auto py-10 px-4 space-y-8 select-none">
            {/* Greeting Header inspired by Claude's elegant style */}
            <div className="space-y-3 animate-fade-in">
              <div className="flex items-center justify-center gap-3">
                {/* Custom sunburst flower symbol / asterisk resembling Claude's */}
                <svg className="w-10 h-10 text-orange-400/90 animate-pulse" viewBox="0 0 100 100" fill="currentColor">
                  {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => (
                    <rect
                      key={angle}
                      x="46"
                      y="14"
                      width="8"
                      height="72"
                      rx="4"
                      transform={`rotate(${angle} 50 50)`}
                      className="origin-center text-[#FF8E24]"
                    />
                  ))}
                  <circle cx="50" cy="50" r="14" className="text-amber-500" />
                </svg>

                {/* Elegant serif-style greeting */}
                <h1 className="text-3xl sm:text-4.5xl font-serif text-[#ffd3a6] tracking-tight font-medium leading-none">
                  {(() => {
                    const hr = new Date().getHours();
                    if (hr < 12) return 'Morning';
                    if (hr < 18) return 'Afternoon';
                    return 'Evening';
                  })()}, Mirzat
                </h1>
              </div>
            </div>

            {/* Luxurious prompt input box resembling Claude's container design */}
            <div className="w-full max-w-xl bg-[#121520] border border-[#23293e] rounded-2xl p-4 flex flex-col space-y-3 focus-within:border-[#FF8E24]/60 focus-within:ring-1 focus-within:ring-[#FF8E24]/30 shadow-2xl transition-all">
              <textarea
                id="landing-message-input"
                rows={3}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    if (inputValue.trim()) {
                      handleSendMessage(e);
                    }
                  }
                }}
                disabled={isSimulating}
                placeholder="Paste a document, an email, or a task description to orchestrate..."
                className="w-full bg-transparent text-sm text-white placeholder-gray-500 focus:outline-none resize-none px-2 pt-1 font-sans leading-relaxed min-h-[55px]"
              />

              {/* Action options row */}
              <div className="flex items-center justify-between pt-2 border-t border-[#1e2330]/50 select-none">
                <button 
                  type="button" 
                  onClick={() => alert("Local datasets & specialized credentials mounted securely inside workspace.")} 
                  className="p-1.5 text-gray-500 hover:text-gray-300 hover:bg-white/[0.03] rounded-lg transition-all"
                  title="Attach workspace documents or source context"
                >
                  <Plus className="w-4.5 h-4.5 text-gray-500" />
                </button>

                <div className="flex items-center gap-2">
                  {/* Model Choice indicator */}
                  <div className="flex items-center gap-1 bg-black/40 hover:bg-black/60 px-2.5 py-1 rounded-full border border-gray-800 text-[10px] font-mono text-gray-400 hover:text-gray-200 cursor-pointer transition-colors max-w-[130px] sm:max-w-none truncate">
                    <span>🦁 Arslan v4.8 High</span>
                    <ChevronDown className="w-3 h-3 text-gray-500" />
                  </div>

                  {/* Micro icon */}
                  <button type="button" className="p-1 text-gray-500 hover:text-gray-300" title="Audio transcription input">
                    <svg className="w-4 h-4 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                      <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 19v4M8 23h8" />
                    </svg>
                  </button>

                  {/* Wave icon */}
                  <button type="button" className="p-1 text-gray-500 hover:text-gray-300" title="Simulated audio feedback channel">
                    <svg className="w-4 h-4 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M3 10v4M6 6v12M9 11v2M12 4v16M15 8v8M18 11v2M21 10v4" />
                    </svg>
                  </button>

                  <button
                    type="button"
                    disabled={isSimulating || !inputValue.trim()}
                    onClick={(e) => {
                      if (inputValue.trim()) {
                        handleSendMessage(e);
                      }
                    }}
                    className="p-1.5 bg-[#FF8E24] hover:bg-[#ff9c3a] disabled:bg-gray-800/80 disabled:text-gray-600 text-black rounded-lg transition-all flex items-center justify-center ml-1"
                  >
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>

            {/* Quick action pill suggestions inspired by Claude suggestions */}
            <div className="w-full max-w-xl text-center space-y-2">
              <span className="text-[10px] font-mono text-gray-600 uppercase tracking-widest block">Start Orchestrating presets</span>
              <div className="flex flex-wrap gap-1.5 justify-center">
                {[
                  { label: "✏️ Code Audit", prompt: "Conduct automatic code analysis on sandbox files to discover vulnerability patterns." },
                  { label: "🎓 Financial Brief", prompt: "Summarize Q1 market ratings and consensus predictions for Blackwell chipsets output." },
                  { label: "💻 Slogan Synthesis", prompt: "Draft optimized copywriting hooks for key promotional tech campaigns with emojis." },
                  { label: "🔍 Drive Fetcher", prompt: "Use Brave registry crawler tool to catalog recent AI deployment metrics." }
                ].map((item, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      setInputValue(item.prompt);
                      document.getElementById('landing-message-input')?.focus();
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-[#121622]/60 hover:bg-[#1f253b] border border-[#1e2330]/80 rounded-full text-[11px] text-gray-400 hover:text-white transition-all cursor-pointer select-none font-sans"
                  >
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          chatHistory.map((msg, index) => {
            const isUser = msg.sender === 'user';
            const isArslan = msg.sender === 'arslan';
            const isSpawn = msg.sender === 'spawn';

            // Quartz Theme Rendering
            if (currentStyle === 'quartz') {
              return (
                <div 
                  key={msg.id} 
                  className={`flex gap-4 ${isUser ? 'justify-end' : ''}`}
                >
                  {/* Avatar left (for system) */}
                  {!isUser && (
                    <div className="flex flex-col items-center select-none">
                      <div className={`w-9 h-9 rounded-xl flex items-center justify-center text-sm font-sans relative ${
                        isArslan
                          ? 'bg-gradient-to-tr from-[#FF8E24] to-yellow-500 text-white shadow-lg shadow-[#FF8E24]/15'
                          : 'bg-[#1a1e2a] border border-[#ff8e24]/30 text-white'
                      }`}>
                        <SFSymbol nameOrEmoji={msg.senderAvatar} className="w-4 h-4 text-white" />
                        <span className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-black ${
                          isArslan ? 'bg-emerald-500' : 'bg-[#FF8E24]'
                        }`} />
                      </div>
                      <span className="text-[9px] text-gray-500 font-mono mt-1 font-semibold">{msg.timestamp}</span>
                    </div>
                  )}

                  {/* Message Bubble */}
                  <div className={`max-w-2xl space-y-3 ${isUser ? 'order-1' : ''}`}>
                    {/* Sender label name */}
                    {!isUser && (
                      <div className="flex items-center gap-1.5 select-none">
                        <span className="text-[11px] font-semibold text-gray-300">{msg.senderName}</span>
                        {isArslan ? (
                          <span className="text-[9px] bg-[#FF8E24]/10 text-[#FF8E24] border border-[#FF8E24]/30 px-1.5 py-0.2 rounded font-semibold font-mono uppercase tracking-wider scale-95">
                            Orchestrator
                          </span>
                        ) : (
                          <div className="flex items-center gap-1 scale-95">
                            <span className="text-[9px] bg-amber-500/10 text-amber-500 border border-amber-500/20 px-1.5 py-0.2 rounded font-mono uppercase tracking-wider font-semibold">
                              Spawn Core
                            </span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Styled Bubble Body */}
                    <div className={`px-4 py-3 rounded-2xl border text-[12.5px] leading-relaxed relative ${
                      isUser
                        ? 'bg-gradient-to-br from-[#FF8E24] to-amber-600 border-[#ffaa45]/50 text-white shadow-md shadow-[#FF8E24]/10 rounded-tr-none'
                        : isArslan
                        ? 'bg-[#151924]/80 backdrop-blur border-[#23293b] text-gray-100 rounded-tl-none shadow-sm shadow-black/40'
                        : 'bg-[#11141d]/90 backdrop-blur border-[#ff8e24]/15 text-gray-200 rounded-tl-none'
                    }`}>
                      {/* Message Content */}
                      <p className="whitespace-pre-line font-sans leading-relaxed">{msg.text}</p>

                      {/* Routed Indicator - specifically asked in prompt */}
                      {msg.routedTo && (
                        <div className="mt-3.5 pt-3 border-t border-[#1e2330]/50 flex items-center gap-2.5 text-[11px] font-mono bg-[#141824]/50 p-2 rounded-lg border border-[#232a3e]">
                          <div className="w-2 h-2 rounded-full bg-[#FF8E24] animate-ping" />
                          <div className="flex items-center gap-1 text-gray-400">
                            <span>Workflow context routed to</span>
                            <span className="text-[#FF8E24] font-semibold flex items-center gap-0.5">
                              <CornerDownRight className="w-3 h-3 inline-block" />
                              {msg.routedTo.spawnName}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* 1. Spawn Intro Card Sub-Component (specifically asked in prompt) */}
                    {msg.spawnIntro && (
                      <div className="bg-gradient-to-b from-[#131722]/90 to-[#0e111a]/95 border border-[#FF8E24]/30 rounded-2xl p-4 shadow-xl shadow-[#FF8E24]/5 space-y-3.5 relative overflow-hidden group">
                        {/* Decorative background glow for card */}
                        <div className="absolute top-0 right-0 w-24 h-24 bg-[#FF8E24]/5 blur-xl group-hover:bg-[#FF8E24]/10 transition-all rounded-full pointer-events-none"></div>
                        
                        <div className="flex items-start gap-3.5">
                          <div className="w-11 h-11 rounded-xl bg-orange-950/25 border border-[#FF8E24]/30 flex items-center justify-center text-xl shadow-inner shadow-[#FF8E24]/10">
                            <SFSymbol nameOrEmoji={msg.spawnIntro.avatarEmoji} className="w-6 h-6" />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <h4 className="text-xs font-bold text-white font-sans">{msg.spawnIntro.name}</h4>
                              <span className="text-[9px] bg-[#FF8E24]/15 text-[#FF8E24] font-mono px-1.5 py-0.5 rounded font-bold uppercase tracking-widest border border-[#FF8E24]/10">Introduced</span>
                            </div>
                            <p className="text-[10px] text-gray-400 font-mono mt-0.5">{msg.spawnIntro.domain}</p>
                          </div>
                        </div>

                        {/* Equipped Capabilities Rendering */}
                        <div className="space-y-2">
                          <div className="text-[10px] text-gray-500 font-mono font-medium tracking-wide uppercase">Equipped Capabilities:</div>
                          <div className="flex flex-wrap gap-1.5">
                            {/* Render Tool tags with 🔧 */}
                            {msg.spawnIntro.tools.map(toolId => {
                              const toolMeta = TOOLS.find(t => t.id === toolId);
                              return (
                                <span 
                                  key={toolId}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-mono bg-[#161a29] text-gray-300 px-2 py-0.8 rounded-lg border border-[#232a3e] hover:border-[#FF8E24]/30 transition-all hover:text-white"
                                >
                                  <span>🔧</span>
                                  <span className="font-semibold">{toolMeta?.name || toolId}</span>
                                </span>
                              );
                            })}
                            {/* Render Skill tags with 📘 */}
                            {msg.spawnIntro.skills.map(skillId => {
                              const skillMeta = SKILLS.find(s => s.id === skillId);
                              return (
                                <span 
                                  key={skillId}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-mono bg-amber-950/10 text-amber-500 px-2 py-0.8 rounded-lg border border-amber-950/40 hover:border-amber-500/30 transition-all"
                                >
                                  <span>📘</span>
                                  <span className="font-semibold">{skillMeta?.name || skillId}</span>
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* 2. Tool-Activity Frame Sub-Component (specifically asked in prompt) */}
                    {msg.toolActivity && (
                      <div className="bg-[#121622] border border-[#232a3f] rounded-2xl shadow-lg shadow-black/30 overflow-hidden text-[11px] font-sans">
                        {/* Header bar */}
                        <div className="bg-[#0b0d14] px-4 py-2.5 flex items-center justify-between border-b border-[#1e2436] select-none">
                          <div className="flex items-center gap-2">
                            <span className="animate-spin text-[#FF8E24]">🌀</span>
                            <span className="font-mono text-gray-400">Tool Socket actively engaged:</span>
                            <span className="flex items-center gap-1 bg-[#FF8E24]/15 text-[#FF8E24] px-2 py-0.5 rounded-md font-mono text-[10px] uppercase font-bold tracking-wider border border-[#FF8E24]/10">
                              {msg.toolActivity.emoji} {msg.toolActivity.toolName}
                            </span>
                          </div>
                          <button 
                            onClick={() => toggleToolCollapse(msg.toolActivity!.id)}
                            className="text-[10px] font-mono text-gray-500 hover:text-[#FF8E24] transition-all bg-[#1b1e2c] border border-[#2d3246] px-2 py-0.5 rounded-md"
                          >
                            {collapsedToolActivities[msg.toolActivity.id] ? "Expand results (Full Log)" : "Collapse"}
                          </button>
                        </div>

                        {/* Collateral body content */}
                        {!collapsedToolActivities[msg.toolActivity.id] ? (
                          <div className="p-4 space-y-3 font-mono">
                            <div className="flex items-start gap-2 bg-black/45 p-2 rounded-lg border border-[#1e2332]/50 text-emerald-400">
                              <span className="text-gray-500 select-none">sh$</span>
                              <span className="text-[10.5px]">{msg.toolActivity.action}</span>
                            </div>
                            <div className="space-y-1 mt-1">
                              <div className="text-gray-500 text-[10px] uppercase">Stdout returns:</div>
                              <p className="text-gray-300 text-[10.5px] bg-[#1a1e2b] p-3 rounded-lg border border-[#2c3349]/50 leading-relaxed whitespace-pre-line border-l-2 border-l-[#FF8E24]">
                                {msg.toolActivity.outputSummary}
                              </p>
                            </div>
                            <div className="flex items-center gap-1 text-[10px] text-[#FF8E24]/70">
                              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 inline mr-0.5" />
                              <span>Instruction execution validated. Sandbox socket gracefully returned 0.</span>
                            </div>
                          </div>
                        ) : (
                          <div className="px-4 py-2 bg-black/20 text-gray-500 text-[10.5px] font-mono flex items-center gap-1.5 border-t border-[#1e2436]/50">
                            <Clock className="w-3 h-3 text-gray-600 inline" />
                            <span>Run details flattened to summary statement: {msg.toolActivity.outputSummary.slice(0, 50)}...</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* 3. Escalation Banner Status Indicator (specifically asked in prompt) */}
                    {msg.escalation && (
                      <div className={`p-4 rounded-2xl border flex items-start gap-3.5 shadow-md ${
                        msg.escalation.status === 'need_raised'
                          ? 'bg-amber-950/15 border-amber-950/60 text-amber-500 shadow-amber-950/5'
                          : msg.escalation.status === 'arslan_resolving'
                          ? 'bg-orange-950/20 border-[#FF8E24]/30 text-[#FF8E24] shadow-[#FF8E24]/5'
                          : msg.escalation.status === 'resolved'
                          ? 'bg-emerald-950/15 border-emerald-950/60 text-emerald-500 shadow-emerald-500/5'
                          : 'bg-red-950/15 border-red-950/60 text-red-500 shadow-red-950/5'
                      }`}>
                        <div className="mt-0.5">
                          {msg.escalation.status === 'need_raised' && <AlertTriangle className="w-4.5 h-4.5 animate-bounce" />}
                          {msg.escalation.status === 'arslan_resolving' && <Cpu className="w-4.5 h-4.5 animate-spin" />}
                          {msg.escalation.status === 'resolved' && <CheckCircle2 className="w-4.5 h-4.5 text-emerald-500" />}
                          {msg.escalation.status === 'refused' && <XOctagon className="w-4.5 h-4.5 text-red-500" />}
                        </div>
                        <div className="space-y-1 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-[11.5px] font-bold font-mono tracking-wide uppercase">
                              {msg.escalation.status === 'need_raised' && "Escalation raised"}
                              {msg.escalation.status === 'arslan_resolving' && "Arslan resolving escalation"}
                              {msg.escalation.status === 'resolved' && "Escalation resolved"}
                              {msg.escalation.status === 'refused' && "Escalation Safety Trigger: REFUSED"}
                            </span>
                            <span className="text-[9px] bg-black/30 font-mono px-1.5 border border-white/5 rounded">
                              From: {msg.escalation.spawnName}
                            </span>
                          </div>
                          <p className="text-[11px] text-gray-300 font-sans leading-relaxed">{msg.escalation.issue}</p>
                          
                          {/* Inner details if context resolution message exists */}
                          {msg.escalation.resolutionMessage && (
                            <div className="mt-2.5 p-2.5 bg-black/50 rounded-lg border border-red-900/40 text-red-400 font-mono text-[10.5px] leading-relaxed">
                              {msg.escalation.resolutionMessage}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Avatar right (for user) */}
                  {isUser && (
                    <div className="flex flex-col items-center select-none">
                      <div className="w-9 h-9 rounded-xl bg-[#1e2330] border border-gray-700 flex items-center justify-center text-sm shadow-md">
                        <SFSymbol nameOrEmoji={msg.senderAvatar} className="w-4 h-4 text-white" />
                      </div>
                      <span className="text-[9px] text-gray-500 font-mono mt-1 font-semibold">{msg.timestamp}</span>
                    </div>
                  )}
                </div>
              );
            }

            // Brutalist Theme Rendering (High-contrast, terminal-like blocks, retro orange elements)
            if (currentStyle === 'brutalist') {
              return (
                <div 
                  key={msg.id} 
                  className={`border-2 border-orange-500/60 p-4 font-mono text-[12px] bg-[#090b10] shadow-[4px_4px_0px_#FF8E24] relative`}
                >
                  {/* Sender Headers */}
                  <div className="flex items-center justify-between pb-2 border-b border-dashed border-gray-800 select-none mb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-amber-500 font-bold flex items-center gap-1.5">
                        [<SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5 inline-block" />] {msg.senderName.toUpperCase()}
                      </span>
                      <span className="text-[10px] px-1 py-0.2 bg-orange-950/20 text-orange-500 border border-orange-500/25">
                        {msg.sender.toUpperCase()}
                      </span>
                    </div>
                    <span className="text-gray-500 text-[10px]">{msg.timestamp}</span>
                  </div>

                  <p className="whitespace-pre-line text-gray-300 font-mono leading-relaxed">{msg.text}</p>

                  {/* Routed branch block */}
                  {msg.routedTo && (
                    <div className="mt-3 p-2 bg-[#FF8E24]/5 border-2 border-[#FF8E24] text-[11px] text-[#FF8E24] uppercase font-bold flex items-center gap-1.5 shadow-[2px_2px_0px_#000]">
                      <span>≫ DELEGATING THREAD DIRECTLY TO {msg.routedTo.spawnName.toUpperCase()}</span>
                    </div>
                  )}

                  {/* Spawn Intro Brutalist version */}
                  {msg.spawnIntro && (
                    <div className="mt-4 border-2 border-orange-500 bg-black p-3 space-y-2 text-[11px]">
                      <div className="flex items-center gap-2 font-bold text-orange-500">
                        <span>SPAWN CREATION INDEX: {msg.spawnIntro.name.toUpperCase()}</span>
                      </div>
                      <p className="text-gray-400 text-[10px]">DOMAIN: {msg.spawnIntro.domain.toUpperCase()}</p>
                      
                      <div className="pt-2 border-t border-gray-900 space-y-1">
                        <span className="text-gray-500 font-bold">EQUIPPED CAPABILITIES:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {msg.spawnIntro.tools.map(toolId => (
                            <span key={toolId} className="px-1.5 py-0.5 bg-black text-gray-300 border border-gray-700">
                              [TOOL] {toolId.toUpperCase()}
                            </span>
                          ))}
                          {msg.spawnIntro.skills.map(skillId => (
                            <span key={skillId} className="px-1.5 py-0.5 bg-black text-orange-500 border border-orange-500">
                              [SKILL] {skillId.toUpperCase()}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Tool Activity Brutalist version */}
                  {msg.toolActivity && (
                    <div className="mt-4 border-2 border-amber-500 bg-[#07090e] p-3 text-[11px] font-mono">
                      <div className="text-amber-500 font-bold uppercase pb-1 border-b border-amber-500/20 flex justify-between items-center">
                        <span>🔧 EXECUTING SOCKET ACTIVITY: {msg.toolActivity.toolName.toUpperCase()}</span>
                        <span className="text-[9px] bg-amber-500 text-black px-1">RUNNING</span>
                      </div>
                      
                      <div className="mt-2 text-gray-300 p-1 bg-black border border-gray-800">
                        <span className="text-gray-500">$</span> {msg.toolActivity.action}
                      </div>

                      <div className="mt-2 text-[#FF8E24]">
                        RETURN VALUE SUMMARY: {msg.toolActivity.outputSummary}
                      </div>
                    </div>
                  )}

                  {/* Brutalist Escalation Panel */}
                  {msg.escalation && (
                    <div className="mt-4 border-2 border-red-500 bg-black p-3 text-[11px]">
                      <div className="text-red-500 font-bold uppercase select-none pb-2 flex justify-between">
                        <span>⚠️ EXTREME PRIORITY ESCALATION INDEX ⚠️</span>
                        <span>{msg.escalation.status.toUpperCase()}</span>
                      </div>
                      <p className="text-gray-300 font-semibold">{msg.escalation.issue.toUpperCase()}</p>
                      {msg.escalation.resolutionMessage && (
                        <div className="mt-2 bg-red-950/20 text-red-500 p-2 border border-red-800">
                          LOG REJECTION DETAILED STATEMENT: {msg.escalation.resolutionMessage.toUpperCase()}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            }

            // Linear Minimal Theme Rendering (Sleek layout, precise margins, subtle borders, thin colors)
            if (currentStyle === 'linear') {
              return (
                <div key={msg.id} className="border-b border-[#1e2330]/40 pb-5 text-[12px] space-y-2">
                  {/* Sender Metadata Row */}
                  <div className="flex items-center gap-2 select-none text-[11px]">
                    <span className="text-gray-500 flex items-center justify-center"><SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5" /></span>
                    <span className="font-bold text-gray-200">{msg.senderName}</span>
                    <span className="text-gray-500 font-mono">•</span>
                    <span className="text-gray-500 font-mono">{msg.timestamp}</span>
                    {isArslan && (
                      <span className="text-[9px] bg-[#1a1c22] text-[#FF8E24] px-1.5 py-0.2 rounded font-mono border border-[#FF8E24]/20 uppercase">
                        Orchestrator
                      </span>
                    )}
                    {!isArslan && !isUser && (
                      <span className="text-[9px] bg-gray-950 text-amber-500 px-1.5 py-0.2 rounded font-mono border border-amber-900/40 uppercase">
                        Spawn • Core
                      </span>
                    )}
                  </div>

                  {/* Body Content */}
                  <p className="whitespace-pre-line text-gray-300 font-sans leading-relaxed text-[12.5px] pl-5">
                    {msg.text}
                  </p>

                  {/* Linear clean route badge */}
                  {msg.routedTo && (
                    <div className="text-[10px] text-gray-500 font-mono flex items-center gap-1.5 pl-5">
                      <span className="text-[#999]">→ Routed process to:</span>
                      <span className="text-[#FF8E24] hover:underline font-bold select-none cursor-pointer">
                        {msg.routedTo.spawnName}
                      </span>
                    </div>
                  )}

                  {/* Linear Minimal Spawn intro */}
                  {msg.spawnIntro && (
                    <div className="pl-5 pt-2">
                      <div className="border border-gray-800 bg-[#0a0d13] rounded-lg p-3 space-y-2.5 max-w-xl">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-white text-[11px]">{msg.spawnIntro.name} Spawn Registry</span>
                          </div>
                          <span className="text-[9px] bg-gray-900 text-gray-400 px-1 py-0.2 rounded font-mono">active</span>
                        </div>
                        <div className="text-[10px] text-gray-500">Capabilities Matrix:</div>
                        <div className="flex flex-wrap gap-1">
                          {msg.spawnIntro.tools.map(toolId => (
                            <span key={toolId} className="text-[10px] bg-[#13151b] border border-gray-800 text-gray-300 px-1.5 py-0.2 rounded">
                              {toolId}
                            </span>
                          ))}
                          {msg.spawnIntro.skills.map(skillId => (
                            <span key={skillId} className="text-[10px] bg-amber-950/15 border border-amber-900/30 text-amber-500 px-1.5 py-0.2 rounded">
                              {skillId}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Linear Minimal Tool activity */}
                  {msg.toolActivity && (
                    <div className="pl-5 pt-2">
                      <div className="border border-gray-800 bg-[#0d0f15]/50 rounded-lg p-2 max-w-xl font-mono text-[10.5px]">
                        <div className="flex items-center gap-1.5 text-gray-400">
                          <Wrench className="w-3.5 h-3.5 text-[#FF8E24]" />
                          <span>Standard Executor tool {msg.toolActivity.toolName}:</span>
                          <span className="text-gray-600 bg-[#121622] px-1 rounded uppercase tracking-wider text-[8px] border border-gray-800">OK</span>
                        </div>
                        <div className="mt-1 text-gray-500 pl-5">
                          {msg.toolActivity.action}
                        </div>
                        <div className="mt-1 pl-5 text-[#FF8E24]">
                          Summary Outcome: {msg.toolActivity.outputSummary}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Linear Minimal Escalation status */}
                  {msg.escalation && (
                    <div className="pl-5 pt-2">
                      <div className="border border-red-950/40 bg-red-950/5 border-l-2 border-l-red-500 rounded-r-lg p-3 max-w-xl">
                        <div className="flex items-center gap-1 text-[10.5px] text-red-500 font-mono font-bold uppercase select-none">
                          <AlertTriangle className="w-3.5 h-3.5" />
                          <span>Escalation Exception - Spawn Access Lockout ({msg.escalation.status})</span>
                        </div>
                        <p className="text-[11px] text-gray-300 mt-1 leading-relaxed">{msg.escalation.issue}</p>
                        {msg.escalation.resolutionMessage && (
                          <p className="mt-2 text-red-400 text-[10px] font-mono whitespace-pre-wrap pl-2 bg-black/40 py-1.5 rounded">{msg.escalation.resolutionMessage}</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            }

            return null;
          })
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input Message Form Panel */}
      {chatHistory.length > 0 && (
        <footer className="p-4 border-t border-[#1e2330] bg-[#0a0c10]/80 backdrop-blur shrink-0 z-10 select-none">
          <form onSubmit={handleSendMessage} className="max-w-4xl mx-auto flex items-center gap-2 relative">
            <input
              id="chat-message-input"
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              disabled={isSimulating}
              placeholder={isSimulating ? "Simulation workflow running..." : "Ask Arslan to orchestrate... (e.g., '@Aletheia write an executive summary')"}
              className="w-full bg-[#121520] border border-[#23293e] hover:border-[#353e5e] focus:border-[#FF8E24]/60 focus:ring-1 focus:ring-[#FF8E24]/30 rounded-xl px-4 py-3 text-xs text-white placeholder-gray-500 focus:outline-none pr-12 transition-all font-sans"
            />
            <button
              id="chat-send-submit"
              type="submit"
              disabled={isSimulating || !inputValue.trim()}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-[#FF8E24] hover:bg-[#ff9c3a] disabled:bg-gray-800 disabled:text-gray-500 disabled:opacity-50 text-black font-bold uppercase rounded-lg transition-all"
            >
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>
          <div className="flex items-center justify-center gap-6 mt-2 text-[10px] text-gray-600 font-mono">
            <span>Enter to execute prompt</span>
            <span>•</span>
            <span className="flex items-center gap-1.5 font-sans">
              <Layers className="w-3.5 h-3.5 text-gray-500" />
              Core Host is sandboxed local client loop
            </span>
          </div>
        </footer>
      )}
    </div>

    {/* Right Pane: Isolated Co-Pilot Private Sandbox (副对话框) */}
    {splitSpawnId && (() => {
      const spawn = spawns.find(s => s.id === splitSpawnId);
      if (!spawn) return null;

      const activeSubChats = subChats[splitSpawnId] || [];
      const activeDraft = subDrafts[splitSpawnId] || '';

      return (
        <div className="w-[45%] border-l border-[#1e2330] bg-[#090b0f] flex flex-col h-full animate-slide-in-right relative overflow-hidden shrink-0 z-20">
          {/* Sandbox Top Header */}
          <div className="h-[52px] border-b border-[#1e2330] px-4.5 bg-[#0a0c10]/80 backdrop-blur flex items-center justify-between select-none shrink-0">
            <div className="flex items-center gap-2.5">
              <span className="text-lg">{spawn.avatarEmoji}</span>
              <div>
                <div className="flex items-center gap-1.5 leading-none">
                  <span className="text-xs font-bold text-white font-sans">{spawn.name}</span>
                  <span className="text-[9px] bg-amber-500/10 text-amber-500 border border-amber-500/20 px-1.5 py-0.2 rounded font-mono font-bold uppercase">
                    Sandbox
                  </span>
                </div>
                <span className="text-[9px] text-[#FF8E24] font-mono mt-1 block uppercase tracking-wider">{spawn.domain}</span>
              </div>
            </div>

            <button 
              onClick={() => setSplitSpawnId(null)}
              className="p-1 text-gray-400 hover:text-white bg-[#10131b] border border-gray-800/80 rounded hover:bg-black/30"
              title="Minimize Sandbox"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Sandbox Content Split */}
          <div className="flex-1 flex flex-col overflow-hidden">
            
            {/* Upper Half: Live Output Draft Previewer Block */}
            <div className="p-4 border-b border-[#141822] bg-[#0c0e14] shrink-0">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-mono text-gray-400 uppercase tracking-wider font-bold block">
                  Active Buffer Draft Deliverable:
                </span>
                <span className="text-[9.5px] font-mono bg-amber-950/20 text-amber-400 border border-amber-500/20 px-1.5 py-0.2 rounded">
                  Live Preview
                </span>
              </div>
              <div className="bg-[#050609] border border-gray-800/80 rounded-xl p-3.5 max-h-[190px] overflow-y-auto font-mono text-[10.5px] text-gray-200 shadow-inner select-text">
                <div className="whitespace-pre-wrap leading-relaxed">{activeDraft}</div>
              </div>
            </div>

            {/* Lower Half: Feed of Sub Instructions Chatter log */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {activeSubChats.map((msg, idx) => {
                const isUserMsg = msg.sender === 'user';
                return (
                  <div key={idx} className={`flex gap-2.5 ${isUserMsg ? 'justify-end' : ''}`}>
                    {!isUserMsg && (
                      <div className="w-7 h-7 rounded-lg bg-orange-950/20 border border-[#FF8E24]/30 flex items-center justify-center text-sm shadow-inner shrink-0">
                        {msg.senderAvatar}
                      </div>
                    )}
                    <div className={`max-w-[82%] rounded-xl p-2.5 text-[11px] leading-relaxed shadow-sm ${
                      isUserMsg 
                        ? 'bg-gradient-to-br from-[#FF8E24] to-amber-600 text-white rounded-tr-none' 
                        : 'bg-[#151924]/90 border border-[#1e2332] text-gray-100 rounded-tl-none'
                    }`}>
                      <p className="whitespace-pre-line leading-normal">{msg.text}</p>
                    </div>
                  </div>
                );
              })}

              {subTyping && (
                <div className="flex gap-2.5 items-center pl-2">
                  <div className="w-5 h-5 rounded-full bg-orange-950/20 flex items-center justify-center text-[10px] shrink-0">
                    {spawn.avatarEmoji}
                  </div>
                  <div className="text-[9px] font-mono text-amber-500 animate-pulse uppercase font-semibold">
                    {spawn.name} calibrating draft variables...
                  </div>
                </div>
              )}
              <div ref={subBottomRef} />
            </div>
          </div>

          {/* Sub Instruct Input form */}
          <div className="p-3 bg-black/40 border-t border-[#1e2330]/60 shrink-0">
            <form onSubmit={handleSendSubMessage} className="flex gap-1.5 relative">
              <input 
                type="text"
                value={subInputValue}
                onChange={(e) => setSubInputValue(e.target.value)}
                placeholder={`Instruct ${spawn.name} to refine draft (e.g. "make it short")...`}
                className="w-full bg-[#111420] border border-[#202638] focus:border-[#FF8E24]/60 focus:ring-1 focus:ring-[#FF8E24]/30 rounded-xl px-3 py-2 text-[10.5px] text-white focus:outline-none placeholder-gray-600 transition-all font-sans"
              />
              <button 
                type="submit"
                disabled={!subInputValue.trim() || subTyping}
                className="p-2 bg-[#FF8E24] text-black rounded-lg hover:bg-[#ffa74a] transition-all disabled:opacity-40 shrink-0"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </form>
          </div>

          {/* Primary Action bar - Merge & Confirm / Cancel */}
          <div className="p-4 bg-[#0a0c10] border-t border-[#1e2330]/80 grid grid-cols-2 gap-2.5 shrink-0 select-none">
            <button
              onClick={() => handleConfirmMergeDraft(spawn.id)}
              className="py-2.5 bg-[#FF8E24] hover:bg-[#ff9d3a] text-black font-extrabold text-[10px] rounded-xl flex items-center justify-center gap-1.5 shadow-md shadow-orange-950/20 active:scale-95 transition-all uppercase tracking-wider font-mono mr-1"
            >
              <CheckCircle2 className="w-4 h-4 text-black" />
              <span>Confirm & Merge</span>
            </button>
            
            <button
              onClick={() => handleDiscardSubSession(spawn.id)}
              className="py-2.5 bg-transparent hover:bg-white/[0.04] text-gray-400 hover:text-white font-semibold text-[10px] rounded-xl border border-gray-800/80 hover:border-gray-700 font-mono transition-all uppercase active:scale-95 flex items-center justify-center gap-1.5"
            >
              <XOctagon className="w-4 h-4 text-rose-500/80" />
              <span>Discard Draft</span>
            </button>
          </div>
        </div>
      );
    })()}
  </div>
</div>
);
}
