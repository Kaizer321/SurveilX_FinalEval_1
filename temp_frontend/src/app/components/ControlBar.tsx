import { Play, Pause, SkipBack, SkipForward, Maximize2, Volume2, Download } from 'lucide-react';

interface ControlBarProps {
  isPlaying: boolean;
  onPlayPause: () => void;
}

export function ControlBar({ isPlaying, onPlayPause }: ControlBarProps) {
  return (
    <div className="bg-[#0f0f0f] border-t border-[#2a2a2a] px-6 py-4">
      <div className="flex items-center justify-between">
        {/* Playback Controls */}
        <div className="flex items-center gap-2">
          <button className="p-2 hover:bg-[#2a2a2a] rounded-lg transition-colors">
            <SkipBack className="w-5 h-5 text-white" />
          </button>
          <button
            onClick={onPlayPause}
            className="p-3 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
          >
            {isPlaying ? (
              <Pause className="w-5 h-5 text-white" />
            ) : (
              <Play className="w-5 h-5 text-white" />
            )}
          </button>
          <button className="p-2 hover:bg-[#2a2a2a] rounded-lg transition-colors">
            <SkipForward className="w-5 h-5 text-white" />
          </button>
        </div>

        {/* Timeline */}
        <div className="flex-1 mx-6">
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400 font-mono">
              {new Date().toLocaleTimeString()}
            </span>
            <div className="flex-1 h-1.5 bg-[#2a2a2a] rounded-full overflow-hidden">
              <div className="h-full bg-blue-600 w-1/3"></div>
            </div>
            <span className="text-xs text-gray-400">Live</span>
          </div>
        </div>

        {/* Additional Controls */}
        <div className="flex items-center gap-2">
          <button className="p-2 hover:bg-[#2a2a2a] rounded-lg transition-colors">
            <Volume2 className="w-5 h-5 text-white" />
          </button>
          <button className="p-2 hover:bg-[#2a2a2a] rounded-lg transition-colors">
            <Download className="w-5 h-5 text-white" />
          </button>
          <button className="p-2 hover:bg-[#2a2a2a] rounded-lg transition-colors">
            <Maximize2 className="w-5 h-5 text-white" />
          </button>
        </div>
      </div>
    </div>
  );
}
