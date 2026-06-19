import React, { useState } from 'react';
import { AppSettings } from '../types';
import { 
  Key, Sliders, Globe, Cpu, Check, Eye, EyeOff, Save,
  Database, Info, AlertCircle, Sparkles
} from 'lucide-react';

interface SettingsScreenProps {
  settings: AppSettings;
  setSettings: React.Dispatch<React.SetStateAction<AppSettings>>;
}

export default function SettingsScreen({ settings, setSettings }: SettingsScreenProps) {
  const [localSettings, setLocalSettings] = useState<AppSettings>({ ...settings });
  const [isSaved, setIsSaved] = useState(false);
  const [showLLMKey, setShowLLMKey] = useState(false);
  const [showSearchKey, setShowSearchKey] = useState(false);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setSettings(localSettings);
    setIsSaved(true);
    setTimeout(() => {
      setIsSaved(false);
    }, 2000);
  };

  return (
    <div className="flex-1 overflow-y-auto bg-[#0d0f15] p-8 select-none relative">
      {/* Decorative Blur Ambient Lights */}
      <div className="absolute bottom-0 left-1/4 w-[30rem] h-[30rem] bg-[#FF8E24]/[0.01] blur-[120px] rounded-full pointer-events-none"></div>

      {/* Header bar */}
      <div className="mb-8">
        <h1 className="text-xl font-bold text-white tracking-tight font-sans">System Diagnostics & Configuration</h1>
        <p className="text-xs text-gray-500 font-sans mt-1">
          Calibrate the neural orchestrator core, assign LLM credential keys, and configure telemetry parameters.
        </p>
      </div>

      <form onSubmit={handleSave} className="max-w-4xl space-y-8">
        
        {/* API Credentials Card */}
        <div className="bg-[#121622]/60 border border-[#1e2330] rounded-2xl p-6 space-y-6">
          <div className="flex items-center gap-2 pb-4 border-b border-[#1e2330]/50 select-none">
            <Key className="w-4.5 h-4.5 text-[#FF8E24]" />
            <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-white leading-none">Security API Credentials</h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* LLM Key Input */}
            <div className="space-y-2">
              <label className="block text-[10.5px] font-mono font-medium text-gray-400 uppercase tracking-wide">
                Primary LLM Provider Secret Key (Host Router)
              </label>
              <div className="relative">
                <input
                  id="settings-llm-key"
                  type={showLLMKey ? "text" : "password"}
                  value={localSettings.apiKeyLLM}
                  onChange={(e) => setLocalSettings(prev => ({ ...prev, apiKeyLLM: e.target.value }))}
                  className="w-full bg-[#0a0c11] border border-[#23293e] focus:border-[#FF8E24]/50 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-4 py-3 text-xs text-white placeholder-gray-600 focus:outline-none pr-12 transition-all font-mono"
                  placeholder="Enter API Secret Key..."
                />
                <button
                  id="toggle-show-llm-key"
                  type="button"
                  onClick={() => setShowLLMKey(!showLLMKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white transition-colors"
                >
                  {showLLMKey ? <EyeOff className="w-4.5 h-4.5" /> : <Eye className="w-4.5 h-4.5" />}
                </button>
              </div>
              <p className="text-[10px] text-gray-500 font-sans leading-relaxed">
                Required to authorize Arslan Prime orchestrator models. Local keychain storage is protected by HMAC sandbox.
              </p>
            </div>

            {/* Cognitive Search Key Input */}
            <div className="space-y-2">
              <label className="block text-[10.5px] font-mono font-medium text-gray-400 uppercase tracking-wide">
                Tavily / Google Search API Private key
              </label>
              <div className="relative">
                <input
                  id="settings-search-key"
                  type={showSearchKey ? "text" : "password"}
                  value={localSettings.apiKeySearch}
                  onChange={(e) => setLocalSettings(prev => ({ ...prev, apiKeySearch: e.target.value }))}
                  className="w-full bg-[#0a0c11] border border-[#23293e] focus:border-[#FF8E24]/50 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-4 py-3 text-xs text-white placeholder-gray-600 focus:outline-none pr-12 transition-all font-mono"
                  placeholder="Enter search provider key..."
                />
                <button
                  id="toggle-show-search-key"
                  type="button"
                  onClick={() => setShowSearchKey(!showSearchKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white transition-colors"
                >
                  {showSearchKey ? <EyeOff className="w-4.5 h-4.5" /> : <Eye className="w-4.5 h-4.5" />}
                </button>
              </div>
              <p className="text-[10px] text-gray-500 font-sans leading-relaxed">
                Allocated to standard spawns carrying "Web Search" capability chips. Ensure live indices limits are sufficient.
              </p>
            </div>
          </div>
        </div>

        {/* Model Architecture Configuration options */}
        <div className="bg-[#121622]/60 border border-[#1e2330] rounded-2xl p-6 space-y-6">
          <div className="flex items-center gap-2 pb-4 border-b border-[#1e2330]/50 select-none">
            <Sliders className="w-4.5 h-4.5 text-[#FF8E24]" />
            <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-white leading-none">Intelligence Engine Calibration</h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* LLM Provider selections */}
            <div className="space-y-2">
              <label className="block text-[10.5px] font-mono font-medium text-gray-400 uppercase tracking-wide">
                Routing LLM orchestrator provider
              </label>
              <select
                id="settings-llm-provider"
                value={localSettings.llmProvider}
                onChange={(e: any) => setLocalSettings(prev => ({ ...prev, llmProvider: e.target.value }))}
                className="w-full bg-[#0a0c11] border border-[#23293e] focus:border-[#FF8E24]/50 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-4 py-3 text-xs text-white placeholder-gray-600 focus:outline-none transition-all font-sans"
              >
                <option value="gemini">Google Gemini AI Studio (Native Engine)</option>
                <option value="openai">OpenAI (GPT-4o / Realtime Socket)</option>
                <option value="anthropic">Claude Anthropic (3.5 Sonnet Router)</option>
              </select>
            </div>

            {/* Router model Selection */}
            <div className="space-y-2">
              <label className="block text-[10.5px] font-mono font-medium text-gray-400 uppercase tracking-wide">
                Active Neural Model Routing Target
              </label>
              <select
                id="settings-llm-model"
                value={localSettings.llmModel}
                onChange={(e) => setLocalSettings(prev => ({ ...prev, llmModel: e.target.value }))}
                className="w-full bg-[#0a0c11] border border-[#23293e] focus:border-[#FF8E24]/50 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-4 py-3 text-xs text-white placeholder-gray-600 focus:outline-none transition-all font-mono"
              >
                <option value="gemini-3.5-flash">gemini-3.5-flash (Highest efficiency, low latency)</option>
                <option value="gemini-3.1-pro-preview">gemini-3.1-pro-preview (Advanced reasoning tier)</option>
                <option value="gemini-2.5-flash-image">gemini-2.5-flash-image (Design renderer active)</option>
                <option value="gpt-4o">gpt-4o-2024-05-13 (Standard external model)</option>
              </select>
            </div>

            {/* Cognitive Search selections */}
            <div className="space-y-2">
              <label className="block text-[10.5px] font-mono font-medium text-gray-400 uppercase tracking-wide">
                Cognitive Search Index Broker
              </label>
              <select
                id="settings-search-provider"
                value={localSettings.searchProvider}
                onChange={(e: any) => setLocalSettings(prev => ({ ...prev, searchProvider: e.target.value }))}
                className="w-full bg-[#0a0c11] border border-[#23293e] focus:border-[#FF8E24]/50 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-4 py-3 text-xs text-white placeholder-gray-600 focus:outline-none transition-all font-sans"
              >
                <option value="tavily">Tavily Search API (Developer Index)</option>
                <option value="google-serp">Google Search Grounding socket</option>
                <option value="bing">Bing Cognitive Services</option>
              </select>
            </div>

            {/* Language Localizations */}
            <div className="space-y-2">
              <label className="block text-[10.5px] font-mono font-medium text-gray-400 uppercase tracking-wide">
                System Language localization
              </label>
              <select
                id="settings-language"
                value={localSettings.language}
                onChange={(e) => setLocalSettings(prev => ({ ...prev, language: e.target.value }))}
                className="w-full bg-[#0a0c11] border border-[#23293e] focus:border-[#FF8E24]/50 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-4 py-3 text-xs text-white placeholder-gray-600 focus:outline-[#FF8E24] focus:outline-none transition-all font-sans"
              >
                <option value="English (US)">English (US) - Standard</option>
                <option value="Chinese (Simplified)">简体中文 (Simplified Chinese)</option>
                <option value="Japanese">日本語 (Japanese)</option>
                <option value="German">Deutsch (German)</option>
              </select>
            </div>

            {/* Theme / Visual Style Select */}
            <div className="space-y-2">
              <label className="block text-[10.5px] font-mono font-medium text-gray-400 uppercase tracking-wide">
                System Interface Visual Mode
              </label>
              <select
                id="settings-theme"
                value={localSettings.theme}
                onChange={(e: any) => {
                  const targetTheme = e.target.value;
                  setLocalSettings(prev => ({ ...prev, theme: targetTheme }));
                  setSettings(prev => ({ ...prev, theme: targetTheme }));
                }}
                className="w-full bg-[#0a0c11] border border-[#23293e] focus:border-[#FF8E24]/50 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-4 py-3 text-xs text-white placeholder-gray-600 focus:outline-[#FF8E24] focus:outline-none transition-all font-sans"
              >
                <option value="dark">Dark Mode (Sleek Slate Dark)</option>
                <option value="light">Light Mode (High-Contrast Pearl Light)</option>
              </select>
            </div>
          </div>
        </div>

        {/* Miscellaneous configurations */}
        <div className="bg-[#121622]/60 border border-[#1e2330] rounded-2xl p-6 space-y-6">
          <div className="flex items-center gap-2 pb-4 border-b border-[#1e2330]/50 select-none">
            <Globe className="w-4.5 h-4.5 text-[#FF8E24]" />
            <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-white leading-none">Diagnostic Parameters</h3>
          </div>

          <div className="space-y-4">
            {/* Toggle telemetry */}
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-xs font-bold text-white font-sans">Active diagnostic analytics telemetry</h4>
                <p className="text-[11px] text-gray-400 font-sans mt-0.5 max-w-xl">
                  Allow self-hosted daemon to transmit runtime performance benchmarks to Arslan central servers. Sensitive credentials or message logs are completely filtered out.
                </p>
              </div>
              <input
                id="settings-telemetry-toggle"
                type="checkbox"
                checked={localSettings.telemetry}
                onChange={(e) => setLocalSettings(prev => ({ ...prev, telemetry: e.target.checked }))}
                className="w-4 h-4 text-[#FF8E24] bg-gray-950 border-gray-700 rounded focus:ring-0 select-none cursor-pointer"
              />
            </div>

            {/* Separation divider */}
            <div className="h-[1px] bg-[#1e2330]/40"></div>

            {/* Spawns synthesis modes */}
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-xs font-bold text-white font-sans">Spawns Synthesis orchestration protocol</h4>
                <p className="text-[11px] text-gray-400 font-sans mt-0.5 max-w-xl">
                  Choose how sub-agents are created. Auto: instant delegation without checks. Interactive: asks user approval on the fly before spinning up new spawns.
                </p>
              </div>
              <select
                id="settings-spawn-mode"
                value={localSettings.spawnMode}
                onChange={(e: any) => setLocalSettings(prev => ({ ...prev, spawnMode: e.target.value }))}
                className="bg-[#0a0c11] border border-[#23293e] focus:outline-none font-sans text-xs text-white rounded-lg p-2"
              >
                <option value="auto">Autonomous Synthesis</option>
                <option value="interactive">Interactive Sandbox Auth</option>
                <option value="strict">Strict Static Lock</option>
              </select>
            </div>
          </div>
        </div>

        {/* Footer actions bar */}
        <div className="flex select-none items-center justify-between pt-4 border-t border-[#1e2330]/60 text-[10.5px] font-mono text-gray-500">
          <div className="flex items-center gap-1.5 matches">
            <Info className="w-4 h-4 text-gray-600" />
            <span>Diagnostics confirm hardware configurations match system boundaries.</span>
          </div>

          <button
            id="settings-save-button"
            type="submit"
            className={`px-4 py-2 text-xs font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1.5 ${
              isSaved
                ? 'bg-emerald-600 text-white'
                : 'bg-[#FF8E24] hover:bg-[#ff9c3a] text-black shadow-lg shadow-[#FF8E24]/10'
            }`}
          >
            {isSaved ? <Check className="w-4 h-4 text-white" /> : <Save className="w-4 h-4" />}
            {isSaved ? "Saved Successfully" : "Commit all changes"}
          </button>
        </div>

      </form>
    </div>
  );
}
