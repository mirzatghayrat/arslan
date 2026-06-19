import React from 'react';
import { 
  TrendingUp, Sparkles, Cpu, CircleUser, Bot, Wrench, 
  Settings, HelpCircle, Terminal, FileText, Paintbrush, 
  Lock, Briefcase, Network, Layers, ShieldCheck, HardDrive, AlertTriangle, Play, RefreshCcw, Box
} from 'lucide-react';

interface SFSymbolProps {
  nameOrEmoji: string;
  className?: string;
}

export default function SFSymbol({ nameOrEmoji, className = "w-4 h-4" }: SFSymbolProps) {
  const norm = (nameOrEmoji || '').trim().toLowerCase();

  // Mapping standard emojis or labels to Apple SF Symbols (via modern Lucide outline icons)
  switch (norm) {
    // Spawns
    case '🦊':
    case 'aletheia':
    case 'spawn-aletheia':
      return <TrendingUp className={`${className} text-[#FF8E24]`} />;
      
    case '🐱':
    case 'huan':
    case 'spawn-huan':
      return <Sparkles className={`${className} text-indigo-400`} />;

    case '🦁':
    case 'arslan':
    case 'orchestrator':
      return <Cpu className={`${className} text-[#FF8E24]`} />;

    // Common Fallbacks
    case 'bot':
    case '🤖':
      return <Bot className={`${className} text-emerald-400`} />;

    case 'user':
    case '👤':
      return <CircleUser className={`${className} text-gray-300`} />;

    case 'tool':
    case 'tools':
    case '🛠️':
    case '🔧':
    case 'wrench':
      return <Wrench className={className} />;

    case 'settings':
    case '⚙️':
      return <Settings className={className} />;

    case 'terminal':
    case '💻':
    case '🖥️':
    case '🧑‍💻':
      return <Terminal className={className} />;

    case 'file':
    case 'doc':
    case '📝':
      return <FileText className={className} />;

    case 'design':
    case 'paint':
    case '🎨':
      return <Paintbrush className={className} />;

    case 'lock':
    case 'secure':
    case '🔒':
      return <Lock className={className} />;

    case 'briefcase':
    case 'bag':
    case '💼':
      return <Briefcase className={className} />;

    case 'network':
    case 'flow':
    case '🔗':
      return <Network className={className} />;

    case 'layers':
    case 'stack':
    case '📚':
      return <Layers className={className} />;

    case 'shield':
    case 'hard':
    case '🛡️':
      return <ShieldCheck className={className} />;

    case 'drive':
    case 'storage':
    case '💾':
      return <HardDrive className={className} />;

    case 'alert':
    case 'warning':
    case '⚠️':
      return <AlertTriangle className={className} />;

    case 'play':
    case '▶️':
      return <Play className={className} />;

    case 'refresh':
    case '🔄':
      return <RefreshCcw className={className} />;

    default:
      // Try to match standard Lucide icons if passed directly
      return <Box className={className} />;
  }
}
