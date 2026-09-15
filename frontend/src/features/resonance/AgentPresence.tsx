import { CircleCheck, CirclePause, Radio, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import "./resonance.css";

export function AgentPresence({ status, label }: { status: string; label: string }) {
  const [sound, setSound] = useState(false);
  const context = useRef<AudioContext | null>(null);
  const previous = useRef(status);
  const active = ["queued", "thinking", "awaiting_execution", "requesting"].includes(status);
  const done = status === "completed";
  const Icon = done ? CircleCheck : active ? Radio : CirclePause;

  useEffect(
    () => () => {
      void context.current?.close();
    },
    [],
  );
  useEffect(() => {
    const changed = previous.current !== status;
    previous.current = status;
    const audio = context.current;
    if (!changed || !sound || !audio || audio.state !== "running") return;
    const oscillator = audio.createOscillator();
    const gain = audio.createGain();
    oscillator.connect(gain);
    gain.connect(audio.destination);
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(done ? 660 : active ? 440 : 294, audio.currentTime);
    gain.gain.setValueAtTime(0, audio.currentTime);
    gain.gain.linearRampToValueAtTime(0.035, audio.currentTime + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.3);
    oscillator.start();
    oscillator.stop(audio.currentTime + 0.32);
    oscillator.onended = () => {
      oscillator.disconnect();
      gain.disconnect();
    };
  }, [status, sound, done, active]);

  return (
    <div className="rs-presence" data-status={status} data-active={active}>
      <span className="rs-presence-orbit" aria-hidden="true">
        <Icon size={23} />
      </span>
      <span role="status">{label}</span>
      <button
        type="button"
        aria-label={sound ? "关闭状态声音" : "开启状态声音"}
        aria-pressed={sound}
        onClick={async () => {
          if (sound) {
            setSound(false);
            return;
          }
          try {
            context.current ??= new AudioContext();
            await context.current.resume();
            setSound(context.current.state === "running");
          } catch {
            setSound(false);
          }
        }}
      >
        {sound ? <Volume2 size={17} /> : <VolumeX size={17} />}
      </button>
    </div>
  );
}
