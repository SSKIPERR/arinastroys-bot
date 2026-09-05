"""Монтажный движок на ffmpeg.

Что умеет:
  * разобрать присланные клипы, найти в каждом самый «живой» кусок
    (есть движение, но не трясёт) и выкинуть дрожь на старте/стопе камеры;
  * привести всё к вертикали 1080x1920 — вертикальное кропом, горизонтальное
    на размытой подложке, чтобы кадр не резался пополам;
  * оживить фотографии медленным наездом (Ken Burns);
  * склеить с кроссфейдами, подложить музыку, приклеить титр и финальную плашку;
  * собрать ролик «до/после» со шторкой.

Всё синхронное, поэтому вызывать через asyncio.to_thread.
"""
from __future__ import annotations

import json
import logging
import math
import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from config import MUSIC_DIR, settings

log = logging.getLogger(__name__)

W, H, FPS = 1080, 1920, 30
CRF = "20"
PRESET = "veryfast"


class VideoError(RuntimeError):
    pass


def _run(args: list[str], timeout: int = 900) -> str:
    log.debug("ffmpeg: %s", " ".join(args[:14]))
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-12:])
        raise VideoError(f"{args[0]} упал: {tail}")
    return p.stdout


# ---------------------------------------------------------------- разбор


@dataclass
class Clip:
    path: Path
    duration: float = 0.0
    width: int = 0
    height: int = 0
    has_audio: bool = False
    is_photo: bool = False
    role: str | None = None          # 'do' | 'posle' | None
    start: float = 0.0               # выбранный кусок
    take: float = 0.0
    score: float = 0.0
    meta: dict = field(default_factory=dict)

    @property
    def vertical(self) -> bool:
        return self.height >= self.width


def probe(path: Path) -> dict:
    out = _run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        timeout=90,
    )
    return json.loads(out)


def describe(path: Path, is_photo: bool = False) -> Clip:
    info = probe(path)
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v:
        raise VideoError(f"в файле нет видеодорожки: {path.name}")

    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    # телефоны пишут поворот в side_data — тогда реальные ширина/высота меняются местами
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = abs(int(sd["rotation"])) % 180
    if rot == 90:
        w, h = h, w

    dur = 0.0
    try:
        dur = float(info.get("format", {}).get("duration") or v.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0

    return Clip(
        path=path,
        duration=dur,
        width=w,
        height=h,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        is_photo=is_photo,
    )


def motion_profile(path: Path, sample_fps: int = 5) -> list[tuple[float, float]]:
    """[(секунда, «сколько движения в кадре»)] — по разнице яркости соседних кадров."""
    try:
        out = _run(
            ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(path),
             "-vf", f"fps={sample_fps},scale=192:-2,signalstats,metadata=print:file=-",
             "-f", "null", "-"],
            timeout=300,
        )
    except VideoError as e:
        log.warning("не смог снять профиль движения с %s: %s", path.name, e)
        return []

    pts, res = None, []
    for line in out.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            pts = float(m.group(1))
            continue
        m = re.search(r"lavfi\.signalstats\.YDIF=([0-9.]+)", line)
        if m and pts is not None:
            res.append((pts, float(m.group(1))))
    return res


def pick_window(clip: Clip, want: float) -> tuple[float, float, float]:
    """Ищем отрезок длиной ~want с ровным движением. Возврат: (старт, длина, оценка)."""
    dur = clip.duration
    if dur <= 0:
        return 0.0, want, 0.0
    # отрезаем дрожь при старте/остановке записи
    head = 0.45 if dur > 2.5 else 0.0
    tail = 0.45 if dur > 2.5 else 0.0
    usable = max(dur - head - tail, 0.4)
    take = min(want, usable)
    if usable <= want + 0.2:
        return head, take, 0.0

    prof = [(t, v) for t, v in motion_profile(clip.path) if head <= t <= dur - tail]
    if len(prof) < 4:
        return head + (usable - take) / 2, take, 0.0

    best_start, best_score = head, -1e9
    step = 0.2
    t = head
    while t + take <= dur - tail:
        window = [v for ts, v in prof if t <= ts <= t + take]
        if len(window) >= 2:
            mean = sum(window) / len(window)
            var = sum((x - mean) ** 2 for x in window) / len(window)
            sd = math.sqrt(var)
            # хотим движение, но ровное: награда за среднее, штраф за рывки
            score = mean - 1.15 * sd
            if score > best_score:
                best_score, best_start = score, t
        t += step
    return best_start, take, best_score


# ---------------------------------------------------------------- нарезка


def _vf_fill(blur_bg: bool) -> str:
    """Приведение любого кадра к 1080x1920."""
    if not blur_bg:
        return (
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,fps={FPS},format=yuv420p"
        )
    return (
        f"split=2[bg][fg];"
        f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"gblur=sigma=28,eq=brightness=-0.12[bgb];"
        f"[fg]scale={W}:-2:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS},format=yuv420p"
    )


def cut_segment(clip: Clip, out: Path, keep_audio: bool) -> Path:
    """Один нормализованный кусок видео."""
    blur_bg = not clip.vertical
    vf = _vf_fill(blur_bg)
    args = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{clip.start:.2f}", "-t", f"{clip.take:.2f}", "-i", str(clip.path),
    ]
    if keep_audio and clip.has_audio:
        args += ["-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "0:a:0",
                 "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]
    else:
        args += ["-f", "lavfi", "-t", f"{clip.take:.2f}", "-i", "anullsrc=r=44100:cl=stereo",
                 "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a",
                 "-c:a", "aac", "-b:a", "128k"]
    args += ["-c:v", "libx264", "-preset", PRESET, "-crf", CRF, "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-video_track_timescale", "15360", str(out)]
    _run(args)
    return out


def still_segment(image: Path, out: Path, dur: float = 2.8, zoom_in: bool = True) -> Path:
    """Фотография с медленным наездом — чтобы кадр не выглядел мёртвым.

    Важно: у зацикленного входа НЕ ставим -t, иначе zoompan размножает каждый
    входной кадр на d выходных и рендер уходит в минуты. Ограничиваем -frames:v.
    """
    frames = max(int(dur * FPS), 1)
    z = "min(1+0.0009*on,1.12)" if zoom_in else "max(1.12-0.0009*on,1.0)"
    sw, sh = W * 2, H * 2
    vf = (
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
        f"zoompan=z='{z}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
        f"setsar=1,format=yuv420p"
    )
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image),
        "-f", "lavfi", "-t", f"{dur:.2f}", "-i", "anullsrc=r=44100:cl=stereo",
        "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a",
        "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", PRESET, "-crf", CRF, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-r", str(FPS),
        "-video_track_timescale", "15360", str(out),
    ])
    return out


def card_segment(image: Path, out: Path, dur: float = 1.8) -> Path:
    """Статичная плашка (титр, финальный экран) с лёгким проявлением."""
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"fade=t=in:st=0:d=0.35,fade=t=out:st={max(dur-0.35,0):.2f}:d=0.35,"
        f"setsar=1,fps={FPS},format=yuv420p"
    )
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-t", f"{dur:.2f}", "-i", str(image),
        "-f", "lavfi", "-t", f"{dur:.2f}", "-i", "anullsrc=r=44100:cl=stereo",
        "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", PRESET, "-crf", CRF, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-r", str(FPS),
        "-video_track_timescale", "15360", str(out),
    ])
    return out


def before_after_segment(before: Path, after: Path, out: Path, hold: float = 2.0) -> Path:
    """Шторка «до → после». Самый сильный формат для стройки."""
    total = hold * 2 + 0.9
    fill = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},format=yuv420p"
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-t", f"{hold+0.9:.2f}", "-i", str(before),
        "-loop", "1", "-t", f"{hold+0.9:.2f}", "-i", str(after),
        "-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=44100:cl=stereo",
        "-filter_complex",
        f"[0:v]{fill}[a];[1:v]{fill}[b];"
        f"[a][b]xfade=transition=wiperight:duration=0.9:offset={hold:.2f},format=yuv420p[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", PRESET, "-crf", CRF, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-r", str(FPS),
        "-video_track_timescale", "15360", str(out),
    ])
    return out


# ---------------------------------------------------------------- склейка


def _duration(path: Path) -> float:
    try:
        return float(probe(path)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return 0.0


def concat_cut(segments: list[Path], out: Path) -> Path:
    """Жёсткая склейка через demuxer — сохраняет звук, никогда не подводит."""
    lst = out.parent / f"{out.stem}_list.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in segments), encoding="utf-8")
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(lst),
        "-c", "copy", str(out),
    ])
    lst.unlink(missing_ok=True)
    return out


def concat_xfade(segments: list[Path], out: Path, t: float = 0.35) -> Path:
    """Кроссфейды. Звук отбрасываем — музыку подложим отдельно."""
    if len(segments) == 1:
        shutil.copy(segments[0], out)
        return out

    durs = [_duration(p) for p in segments]
    if any(d <= t + 0.1 for d in durs):
        t = max(min(min(durs) - 0.15, 0.35), 0.12)

    inputs: list[str] = []
    for p in segments:
        inputs += ["-i", str(p)]

    parts, prev, acc = [], "[0:v]", 0.0
    for i in range(1, len(segments)):
        acc += durs[i - 1]
        offset = acc - t * i
        label = f"[x{i}]" if i < len(segments) - 1 else "[v]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={t:.2f}:offset={max(offset,0.05):.2f}{label}"
        )
        prev = label
    graph = ";".join(parts)

    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
        "-filter_complex", graph, "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", PRESET, "-crf", CRF, "-pix_fmt", "yuv420p",
        "-r", str(FPS), str(out),
    ])
    return out


def pick_music() -> Path | None:
    tracks = sorted(
        p for p in MUSIC_DIR.iterdir()
        if p.suffix.lower() in {".mp3", ".m4a", ".wav", ".aac", ".ogg"}
    ) if MUSIC_DIR.exists() else []
    return random.choice(tracks) if tracks else None


def add_music(video: Path, out: Path, music: Path | None, keep_original: bool) -> Path:
    """Музыка под ролик. Если оставляем живой звук — музыка уходит на задний план."""
    if music is None:
        shutil.copy(video, out)
        return out

    dur = _duration(video)
    fade_out = max(dur - 1.2, 0.1)
    vol = settings.music_volume * (0.30 if keep_original else 1.0)
    has_audio = keep_original and bool(
        [s for s in probe(video).get("streams", []) if s.get("codec_type") == "audio"]
    )

    music_chain = (
        f"[1:a]volume={vol:.2f},afade=t=in:st=0:d=1.0,"
        f"afade=t=out:st={fade_out:.2f}:d=1.2,atrim=0:{dur:.2f},asetpts=N/SR/TB[m]"
    )
    if has_audio:
        graph = music_chain + ";[0:a]volume=1.0[o];[o][m]amix=inputs=2:duration=first:dropout_transition=0[a]"
    else:
        graph = music_chain + ";[m]anull[a]"

    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-stream_loop", "-1", "-i", str(music),
        "-filter_complex", graph,
        "-map", "0:v", "-map", "[a]", "-shortest",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(out),
    ])
    return out


# ---------------------------------------------------------------- субтитры


def burn_subtitles(video: Path, out: Path, model_size: str) -> Path:
    """Распознаём речь прораба и вжигаем субтитры. Нужен faster-whisper."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        log.info("faster-whisper не установлен — субтитры пропускаю")
        shutil.copy(video, out)
        return out

    wav = video.with_suffix(".wav")
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
          "-vn", "-ac", "1", "-ar", "16000", str(wav)])

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(wav), language="ru", vad_filter=True)

    def ts(x: float) -> str:
        h, r = divmod(x, 3600)
        m, s = divmod(r, 60)
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: Def,Oswald,64,&H00FFFFFF,&H00000000,&H90000000,-1,3,0,0,2,60,60,220,204",
        "[Events]", "Format: Layer,Start,End,Style,Text",
    ]
    n = 0
    for seg in segments:
        text = (seg.text or "").strip().replace("\n", " ")
        if not text:
            continue
        n += 1
        lines.append(f"Dialogue: 0,{ts(seg.start)},{ts(seg.end)},Def,{text}")
    ass = video.with_suffix(".ass")
    ass.write_text("\n".join(lines), encoding="utf-8")
    wav.unlink(missing_ok=True)

    if n == 0:
        shutil.copy(video, out)
        return out

    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-vf", f"subtitles={ass.as_posix()}:fontsdir={(Path(__file__).parent.parent/'assets'/'fonts').as_posix()}",
        "-c:a", "copy", "-c:v", "libx264", "-preset", PRESET, "-crf", CRF,
        "-pix_fmt", "yuv420p", str(out),
    ])
    ass.unlink(missing_ok=True)
    return out


# ---------------------------------------------------------------- сборка


def build_reel(
    *,
    videos: list[Path],
    photos: list[Path],
    before_after: list[tuple[Path, Path]] | None = None,
    title_card: Path | None = None,
    outro_card: Path | None = None,
    out_path: Path,
    max_seconds: float | None = None,
    keep_original_audio: bool | None = None,
    workdir: Path | None = None,
) -> dict:
    """Главная функция: из сырых файлов делает готовый вертикальный ролик.

    Возвращает отчёт: что вошло, сколько длится, какая музыка.
    """
    max_seconds = max_seconds or settings.video_max_seconds
    keep_audio = settings.keep_original_audio if keep_original_audio is None else keep_original_audio
    tmp = Path(workdir or tempfile.mkdtemp(prefix="reel_"))
    tmp.mkdir(parents=True, exist_ok=True)

    report: dict = {"used_videos": 0, "used_photos": 0, "pairs": 0, "skipped": []}
    segments: list[Path] = []
    idx = 0

    # 1. титр
    if title_card and title_card.exists():
        idx += 1
        segments.append(card_segment(title_card, tmp / f"s{idx:02d}.mp4", 1.7))

    # 2. до/после — самый сильный кусок, ставим ближе к началу
    for b, a in (before_after or []):
        if b.exists() and a.exists():
            idx += 1
            segments.append(before_after_segment(b, a, tmp / f"s{idx:02d}.mp4"))
            report["pairs"] += 1

    # 3. видео: у каждого берём лучший кусок
    budget = max_seconds - sum(_duration(s) for s in segments) - (2.0 if outro_card else 0)
    clips: list[Clip] = []
    for p in videos:
        try:
            c = describe(p)
        except VideoError as e:
            report["skipped"].append(f"{p.name}: {e}")
            continue
        if c.duration < 0.6:
            report["skipped"].append(f"{p.name}: слишком короткий")
            continue
        clips.append(c)

    if clips:
        per = min(settings.video_clip_seconds, max(budget / max(len(clips), 1), 1.4))
        for c in clips:
            c.start, c.take, c.score = pick_window(c, per)
        # если бюджета всё равно не хватает — оставляем самые «живые»
        clips.sort(key=lambda c: c.score, reverse=True)
        total = 0.0
        chosen: list[Clip] = []
        for c in clips:
            if total + c.take > budget and chosen:
                report["skipped"].append(f"{c.path.name}: не влез в хронометраж")
                continue
            chosen.append(c)
            total += c.take
        # снимаем обратно в порядке присланного, чтобы не ломать логику съёмки
        chosen.sort(key=lambda c: videos.index(c.path))
        for c in chosen:
            idx += 1
            segments.append(cut_segment(c, tmp / f"s{idx:02d}.mp4", keep_audio))
            report["used_videos"] += 1
        budget -= total

    # 4. фото добираем, если осталось время
    if photos and budget > 2.0:
        per_photo = 2.6
        room = int(budget // per_photo)
        for i, p in enumerate(photos[:room]):
            idx += 1
            segments.append(still_segment(p, tmp / f"s{idx:02d}.mp4", per_photo, zoom_in=(i % 2 == 0)))
            report["used_photos"] += 1

    if not segments:
        raise VideoError("нечего монтировать: не нашёл ни одного пригодного файла")

    # 5. финальная плашка
    if outro_card and outro_card.exists():
        idx += 1
        segments.append(card_segment(outro_card, tmp / f"s{idx:02d}.mp4", 2.0))

    # 6. склейка
    joined = tmp / "joined.mp4"
    mode = settings.video_transition
    if keep_audio or mode == "cut" or len(segments) < 2:
        concat_cut(segments, joined)
    else:
        try:
            concat_xfade(segments, joined)
        except VideoError as e:
            log.warning("кроссфейды не собрались (%s) — склеиваю встык", e)
            concat_cut(segments, joined)

    # 7. музыка
    music = pick_music()
    with_music = tmp / "music.mp4"
    add_music(joined, with_music, music, keep_audio)
    report["music"] = music.name if music else None

    # 8. субтитры (только если оставили живой звук)
    final_src = with_music
    if keep_audio and settings.whisper_model:
        subbed = tmp / "subbed.mp4"
        try:
            burn_subtitles(with_music, subbed, settings.whisper_model)
            final_src = subbed
        except Exception as e:  # noqa: BLE001
            log.warning("субтитры не получились: %s", e)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(final_src), str(out_path))
    report["duration"] = round(_duration(out_path), 1)
    report["size_mb"] = round(out_path.stat().st_size / 1024 / 1024, 1)
    return report
