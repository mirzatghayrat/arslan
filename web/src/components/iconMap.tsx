/**
 * Central icon map — returns a lucide-react icon component for a given
 * tool/skill/spawn id or emoji glyph key. Use this instead of rendering
 * emoji glyphs directly in UI iconography.
 */
import React from 'react';
import {
  Search,
  TrendingUp,
  Terminal,
  Palette,
  Mail,
  Database,
  Wrench,
  PenLine,
  BarChart3,
  BookOpen,
  LineChart,
  Shield,
  Brain,
  Bot,
  User,
  Cpu,
  Sparkles,
  Box,
  RefreshCcw,
  Lock,
} from 'lucide-react';

/** Returns a Lucide icon JSX element for tool/skill ids, spawn avatar ids, or emoji glyphs. */
export function getIcon(key: string, className = 'w-4 h-4'): React.ReactElement {
  const norm = (key || '').trim().toLowerCase();

  switch (norm) {
    // ── Tool IDs ──────────────────────────────────────────────────────────────
    case 'web-search':
    case '🔍':
      return <Search className={className} />;

    case 'stock-data':
    case '📈':
      return <TrendingUp className={className} />;

    case 'py-exec':
    case '🐍':
      return <Terminal className={className} />;

    case 'canvas-render':
    case '🎨':
      return <Palette className={className} />;

    case 'gmail-broker':
    case '📧':
      return <Mail className={className} />;

    case 'spanner-db':
    case '🧱':
      return <Database className={className} />;

    // ── Skill IDs ─────────────────────────────────────────────────────────────
    case 'seo-opt':
    case '✍️':
      return <PenLine className={className} />;

    case 'financial-res':
    case '📊':
      return <BarChart3 className={className} />;

    case 'infographic-design':
    case '📘':
      return <BookOpen className={className} />;

    case 'stat-analysis':
    case '📉':
      return <LineChart className={className} />;

    case 'vuln-test':
    case '🛡️':
      return <Shield className={className} />;

    // ── Generic tool/skill fallbacks ──────────────────────────────────────────
    case 'tool':
    case '🔧':
    case 'wrench':
      return <Wrench className={className} />;

    case 'skill':
    case '🧠':
      return <Brain className={className} />;

    // ── Spawn / actor avatars ─────────────────────────────────────────────────
    case 'spawn-aletheia':
    case '🦊':
      return <TrendingUp className={className} />;

    case 'spawn-huan':
    case '🐱':
      return <Sparkles className={className} />;

    // Generic spawn / bot
    case '🤖':
    case 'bot':
      return <Bot className={className} />;

    // User / operator
    case '🦁':
    case 'user':
    case 'arslan':
    case 'orchestrator':
      return <Cpu className={className} />;

    case '👤':
      return <User className={className} />;

    // Locked / restricted
    case '🔒':
    case 'lock':
      return <Lock className={className} />;

    // Refresh / spinning state
    case '🌀':
    case 'refresh':
      return <RefreshCcw className={className} />;

    // Default fallback
    default:
      return <Box className={className} />;
  }
}
