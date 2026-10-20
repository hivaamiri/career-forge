"""Telegram Interactive Handler: Processes inline button callbacks and administrative commands."""

from __future__ import annotations

import html
import logging
from typing import Any, Callable, Dict, List, Optional

from src.bridge_careerops import queue_job_to_careerops
from src.config import AppConfig
from src.db import Database
from src.notifier import TelegramNotifier

logger = logging.getLogger(__name__)


def _escape(text: str) -> str:
    return html.escape(str(text), quote=False)


class TelegramCallbackHandler:
    """Polls Telegram updates for inline button callbacks and interactive text commands."""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        notifier: Optional[TelegramNotifier] = None,
        on_config_change: Optional[Callable[[], None]] = None,
        on_sweep_request: Optional[Callable[[], Dict[str, int]]] = None,
    ):
        self.config = config
        self.db = db
        self.notifier = notifier or TelegramNotifier(
            bot_token=config.telegram.bot_token, chat_id=config.telegram.chat_id
        )
        self.pipeline_path = config.career_ops.pipeline_path
        self.on_config_change = on_config_change
        self.on_sweep_request = on_sweep_request
        self._last_update_id: Optional[int] = None

    def process_updates(self, timeout: int = 5) -> int:
        """Fetch and process pending updates (callback queries & text commands)."""
        try:
            offset = (self._last_update_id + 1) if self._last_update_id is not None else None
            data = self.notifier.get_updates(offset=offset, timeout=timeout)
        except Exception as e:
            logger.warning(f"Failed to fetch Telegram updates: {e}")
            return 0

        updates = data.get("result", [])
        processed = 0

        for update in updates:
            update_id = update.get("update_id")
            if update_id is not None:
                self._last_update_id = update_id

            # 1. Handle Inline Button Callback Queries
            callback = update.get("callback_query")
            if callback:
                self._handle_callback(callback)
                processed += 1
                continue

            # 2. Handle Document / CV Uploads
            message = update.get("message")
            if message:
                document = message.get("document")
                if document:
                    self._handle_document(message, document)
                    processed += 1
                    continue

                # 3. Handle Text Commands
                if self._handle_message(message):
                    processed += 1

        return processed

    def _handle_callback(self, callback: Dict[str, Any]) -> None:
        """Handle inline button clicks like [Queue Career-Ops]."""
        callback_id = callback.get("id")
        callback_data = callback.get("data", "")

        job_id = None
        if callback_data.startswith("q:"):
            job_id = callback_data[len("q:") :].strip()
        elif callback_data.startswith("queue:"):
            job_id = callback_data[len("queue:") :].strip()

        if not job_id:
            return

        logger.info(f"Received Queue Career-Ops callback for job_id={job_id}")
        success, message = queue_job_to_careerops(
            job_id=job_id,
            db=self.db,
            pipeline_path=self.pipeline_path,
        )

        notification_text = (
            "✅ Queued into Career-Ops pipeline!"
            if success
            else f"ℹ️ {message}"
        )

        if callback_id:
            try:
                self.notifier.answer_callback_query(
                    callback_query_id=callback_id,
                    text=notification_text,
                )
            except Exception as err:
                logger.warning(f"Failed to answer callback query: {err}")

        # When queued, trigger automated evaluation and report match score
        if success:
            try:
                from src.career_ops.pipeline_manager import PipelineManager
                mgr = PipelineManager(pipeline_path=self.pipeline_path)
                eval_results = mgr.evaluate_all()
                for entry, ev in eval_results:
                    if entry.company in message or job_id in entry.url:
                        self.notifier.send_message(
                            f"🎯 <b>Match Score: {ev.overall_score}% ({ev.classification.split(' ')[0]})</b>\n"
                            f"📋 <b>Role:</b> {_escape(entry.role)} @ {_escape(entry.company)}\n"
                            f"✅ <b>Matched:</b> {_escape(', '.join(ev.matched_skills[:6])) or 'Allgemeine Passung'}\n"
                            f"💡 <i>Type /generate to draft tailored cover letter & resume!</i>"
                        )
                        break
            except Exception as ev_err:
                logger.warning(f"Auto-evaluation error: {ev_err}")

    def _handle_document(self, message: Dict[str, Any], document: Dict[str, Any]) -> None:
        """Handle incoming CV document files (PDF, Markdown, Text)."""
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != str(self.config.telegram.chat_id):
            return

        file_id = document.get("file_id")
        file_name = document.get("file_name", "uploaded_cv.pdf")
        if not file_id:
            return

        self.notifier.send_message(f"📥 <i>Downloading document '{_escape(file_name)}'...</i>")

        try:
            from pathlib import Path
            from src.career_ops.profile_manager import ProfileManager

            file_meta = self.notifier.get_file(file_id)
            file_path = file_meta.get("result", {}).get("file_path")
            if not file_path:
                self.notifier.send_message("❌ Failed to resolve document download URL from Telegram.")
                return

            raw_bytes = self.notifier.download_file(file_path)
            ext = Path(file_name).suffix or ".pdf"
            dest_dir = Path("career-ops/config")
            dest_dir.mkdir(parents=True, exist_ok=True)
            local_path = dest_dir / f"uploaded_cv{ext}"
            local_path.write_bytes(raw_bytes)

            pm = ProfileManager()
            extracted_text = pm.extract_text_from_file(local_path)
            changes = pm.ingest_cv_text(extracted_text, source_filename=file_name)

            skills_count = len(changes.get("analytical_methods", [])) + len(changes.get("quality_and_regulations", []))
            reply = [
                "✅ <b>CV Successfully Ingested!</b>\n",
                f"📄 <b>File:</b> {_escape(file_name)} ({len(raw_bytes) // 1024} KB)",
            ]
            if "name" in changes:
                reply.append(f"👤 <b>Extracted Name:</b> {_escape(changes['name'])}")
            if "email" in changes:
                reply.append(f"📧 <b>Extracted E-Mail:</b> {_escape(changes['email'])}")
            if "phone" in changes:
                reply.append(f"📱 <b>Extracted Phone:</b> {_escape(changes['phone'])}")
            if "location" in changes:
                reply.append(f"📍 <b>Extracted Location:</b> {_escape(changes['location'])}")
            if skills_count > 0:
                skills_preview = ", ".join((changes.get("analytical_methods", []) + changes.get("quality_and_regulations", []))[:8])
                reply.append(f"🔬 <b>Identified Skills ({skills_count}):</b> {_escape(skills_preview)}")

            reply.append("\n💡 <i>Type /profile to view your profile, or /evaluate to re-score queued jobs!</i>")
            self.notifier.send_message("\n".join(reply))

        except Exception as e:
            logger.error(f"Error handling document: {e}", exc_info=True)
            self.notifier.send_message(f"❌ Error ingesting document: {_escape(str(e))}")

    def _handle_message(self, message: Dict[str, Any]) -> bool:
        """Handle text commands for viewing and modifying scraping settings."""
        chat_id = str(message.get("chat", {}).get("id", ""))
        # Verify sender matches authorized chat
        if chat_id != str(self.config.telegram.chat_id):
            logger.warning(f"Ignored message from unauthorized chat_id: {chat_id}")
            return False

        text = (message.get("text") or "").strip()
        if not text.startswith("/"):
            return False

        parts = text.split(maxsplit=1)
        command = parts[0].lower().split("@")[0]  # strip bot username if sent in group
        args = parts[1].strip() if len(parts) > 1 else ""

        logger.info(f"Received Telegram command: {command} with args: '{args}'")

        if command in ["/start", "/help"]:
            self._cmd_help()
        elif command in ["/config", "/settings"]:
            self._cmd_show_config()
        elif command == "/add_keyword":
            self._cmd_add_keyword(args)
        elif command in ["/del_keyword", "/remove_keyword"]:
            self._cmd_del_keyword(args)
        elif command == "/set_keywords":
            self._cmd_set_keywords(args)
        elif command == "/add_location":
            self._cmd_add_location(args)
        elif command in ["/del_location", "/remove_location"]:
            self._cmd_del_location(args)
        elif command == "/set_locations":
            self._cmd_set_locations(args)
        elif command == "/set_radius":
            self._cmd_set_radius(args)
        elif command == "/add_company":
            self._cmd_add_company(args)
        elif command in ["/del_company", "/remove_company"]:
            self._cmd_del_company(args)
        elif command in ["/sweep", "/run", "/scan"]:
            self._cmd_trigger_sweep()
        elif command == "/pipeline":
            self._cmd_show_pipeline()
        elif command == "/evaluate":
            self._cmd_trigger_evaluate()
        elif command == "/generate":
            self._cmd_trigger_generate()
        elif command == "/profile":
            self._cmd_show_profile()
        elif command == "/set_name":
            self._cmd_set_name(args)
        elif command == "/set_title":
            self._cmd_set_title(args)
        elif command == "/set_contact":
            self._cmd_set_contact(args)
        elif command == "/add_skill":
            self._cmd_add_skill(args)
        elif command == "/set_skills":
            self._cmd_set_skills(args)
        elif command == "/set_salary":
            self._cmd_set_salary(args)
        elif command == "/set_availability":
            self._cmd_set_availability(args)
        elif command == "/feed_cv":
            self._cmd_feed_cv(args)
        elif command == "/feed_template":
            self._cmd_feed_template(args)
        elif command == "/reset_config":
            self._cmd_reset_config()
        else:
            self.notifier.send_message(
                f"❓ Unknown command: <code>{_escape(command)}</code>\n\nType /help to see all available commands."
            )
        return True

    def _get_active_keywords(self) -> List[str]:
        return list(
            self.db.get_setting("keywords", self.config.arbeitsagentur.keywords)
        )

    def _get_active_locations(self) -> List[str]:
        return list(
            self.db.get_setting("locations", self.config.arbeitsagentur.locations)
        )

    def _get_active_radius(self) -> int:
        return int(
            self.db.get_setting("radius_km", self.config.arbeitsagentur.radius_km)
        )

    def _get_active_companies(self) -> List[str]:
        return list(
            self.db.get_setting("personio_companies", self.config.ats.personio_companies)
        )

    def _notify_change(self) -> None:
        if self.on_config_change:
            try:
                self.on_config_change()
            except Exception as e:
                logger.error(f"Error applying dynamic configuration: {e}")

    def _cmd_help(self) -> None:
        help_text = (
            "🤖 <b>Job Pulse & Career-Ops Command Center</b>\n\n"
            "<b>🎯 Career-Ops Application Engine:</b>\n"
            "• /pipeline — View active pipeline status and match scores\n"
            "• /evaluate — Run match scoring against your candidate profile\n"
            "• /generate — Generate tailored German Anschreiben & CV (HTML & MD)\n\n"
            "<b>👤 Candidate Profile & CV Configuration:</b>\n"
            "• <i>Upload Document:</i> Send your CV (.pdf, .txt, .md) directly in chat!\n"
            "• /profile — View current candidate profile & skills\n"
            "• /set_name &lt;name&gt; — Set candidate name\n"
            "• /set_title &lt;title&gt; — Set title (e.g. <code>/set_title Chemiker / M.Sc. Analytik</code>)\n"
            "• /set_contact &lt;email | phone | city&gt; — Update contact details\n"
            "• /add_skill &lt;skill1, skill2&gt; — Add skills (e.g. HPLC, GC-MS, GMP)\n"
            "• /set_skills &lt;list&gt; — Overwrite full skills list\n"
            "• /set_salary &lt;text&gt; — Update salary expectation\n"
            "• /set_availability &lt;text&gt; — Update notice period / start date\n"
            "• /feed_cv &lt;text&gt; — Paste raw CV text into chat\n"
            "• /feed_template &lt;text&gt; — Save custom cover letter template\n\n"
            "<b>⚙️ View & Reset Settings:</b>\n"
            "• /config — Display active keywords, locations & radius\n"
            "• /reset_config — Revert all overrides to config.yaml defaults\n\n"
            "<b>🔍 Keyword Management:</b>\n"
            "• /add_keyword &lt;text&gt; — Add keyword(s)\n"
            "• /del_keyword &lt;text&gt; — Remove keyword\n"
            "• /set_keywords &lt;k1, k2, ...&gt; — Overwrite full keyword list\n\n"
            "<b>📍 Location Management:</b>\n"
            "• /add_location &lt;city&gt; — Add target city/region\n"
            "• /del_location &lt;city&gt; — Remove target city\n"
            "• /set_locations &lt;loc1, loc2, ...&gt; — Overwrite location list\n\n"
            "<b>📏 Search Radius:</b>\n"
            "• /set_radius &lt;km&gt; — Set search radius in km\n\n"
            "<b>🏢 Target Personio Companies:</b>\n"
            "• /add_company &lt;slug&gt; — Add target company board\n"
            "• /del_company &lt;slug&gt; — Remove target company\n\n"
            "<b>🚀 On-Demand Actions:</b>\n"
            "• /sweep — Trigger an immediate live scan across all scrapers"
        )
        self.notifier.send_message(help_text)

    def _cmd_show_pipeline(self) -> None:
        try:
            from src.career_ops.pipeline_manager import PipelineManager
            mgr = PipelineManager(pipeline_path=self.pipeline_path)
            entries = mgr.load_entries()
            if not entries:
                self.notifier.send_message(
                    "ℹ️ No jobs currently in pipeline. Tap <b>[📥 Queue Career-Ops]</b> on any job alert to add positions!"
                )
                return

            lines = ["📋 <b>Career-Ops Application Pipeline:</b>\n"]
            for idx, e in enumerate(entries, start=1):
                lines.append(
                    f"<b>{idx}. {_escape(e.company)}</b>\n"
                    f"   💼 {_escape(e.role)}\n"
                    f"   📍 {_escape(e.location)} | 🏷 <b>{_escape(e.status)}</b>\n"
                    f"   🎯 <b>Score:</b> {_escape(e.match_score)}\n"
                )
            lines.append("💡 <i>Use /evaluate to update scores or /generate to build application documents.</i>")
            self.notifier.send_message("\n".join(lines))
        except Exception as e:
            logger.error(f"Error displaying pipeline: {e}")
            self.notifier.send_message(f"❌ Error loading pipeline: {_escape(str(e))}")

    def _cmd_trigger_evaluate(self) -> None:
        self.notifier.send_message("🔍 <i>Scraping job descriptions and scoring against your profile...</i>")
        try:
            from src.career_ops.pipeline_manager import PipelineManager
            mgr = PipelineManager(pipeline_path=self.pipeline_path)
            results = mgr.evaluate_all()
            if not results:
                self.notifier.send_message("ℹ️ No queued positions pending evaluation. Tap [📥 Queue Career-Ops] on new alerts first.")
                return

            msg = [f"🎯 <b>Evaluated {len(results)} Position(s):</b>\n"]
            for entry, ev in results:
                msg.append(
                    f"• <b>{_escape(entry.company)}</b>: <b>{ev.overall_score}%</b> ({ev.classification.split(' ')[0]})\n"
                    f"  Role: {_escape(entry.role)}\n"
                    f"  Matched: {_escape(', '.join(ev.matched_skills[:5])) or 'Allgemeine Passung'}\n"
                )
            msg.append("\n💡 <i>Type /generate to produce customized cover letters & CVs.</i>")
            self.notifier.send_message("\n".join(msg))
        except Exception as e:
            logger.error(f"Error evaluating pipeline: {e}")
            self.notifier.send_message(f"❌ Error during evaluation: {_escape(str(e))}")

    def _cmd_trigger_generate(self) -> None:
        self.notifier.send_message("✍️ <i>Generating tailored German cover letters & CVs...</i>")
        try:
            from src.career_ops.pipeline_manager import PipelineManager
            mgr = PipelineManager(pipeline_path=self.pipeline_path)
            mgr.evaluate_all()
            paths = mgr.generate_all_applications()
            if not paths:
                self.notifier.send_message("ℹ️ No positions ready. Tap [📥 Queue Career-Ops] on a job first!")
                return

            msg = [f"🎉 <b>Generated {len(paths)} Tailored Application Package(s):</b>\n"]
            for p in paths:
                msg.append(
                    f"• <b>{_escape(p.name)}</b>\n"
                    f"  📄 <code>anschreiben.html</code> & <code>lebenslauf.html</code>\n"
                    f"  📁 <code>career-ops/data/applications/{_escape(p.name)}/</code>\n"
                )
            msg.append("💡 <i>Files are ready for print / PDF export in your career-ops directory!</i>")
            self.notifier.send_message("\n".join(msg))
        except Exception as e:
            logger.error(f"Error generating applications: {e}")
            self.notifier.send_message(f"❌ Error generating applications: {_escape(str(e))}")

    def _cmd_show_config(self) -> None:
        keywords = self._get_active_keywords()
        locations = self._get_active_locations()
        radius = self._get_active_radius()
        companies = self._get_active_companies()

        kw_bullets = "\n".join([f"  • {_escape(k)}" for k in keywords]) if keywords else "  <i>(none)</i>"
        loc_bullets = "\n".join([f"  • {_escape(l)}" for l in locations]) if locations else "  <i>(none)</i>"
        comp_bullets = "\n".join([f"  • {_escape(c)}" for c in companies]) if companies else "  <i>(none)</i>"

        msg = (
            "⚙️ <b>Active Scraping Configuration</b>\n\n"
            f"🔍 <b>Search Keywords ({len(keywords)}):</b>\n{kw_bullets}\n\n"
            f"📍 <b>Locations ({len(locations)}):</b>\n{loc_bullets}\n\n"
            f"📏 <b>Radius:</b> {radius} km\n\n"
            f"🏢 <b>Target Personio ATS ({len(companies)}):</b>\n{comp_bullets}\n\n"
            "💡 <i>Tip: Use /add_keyword, /add_location, /set_radius or /help to modify.</i>"
        )
        self.notifier.send_message(msg)

    def _cmd_add_keyword(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/add_keyword &lt;keyword or comma-separated list&gt;</code>")
            return

        new_items = [k.strip() for k in args.split(",") if k.strip()]
        current = self._get_active_keywords()
        added = []
        for item in new_items:
            if not any(item.lower() == c.lower() for c in current):
                current.append(item)
                added.append(item)

        if not added:
            self.notifier.send_message("ℹ️ Specified keyword(s) already exist in configuration.")
            return

        self.db.set_setting("keywords", current)
        self._notify_change()

        added_str = ", ".join([f"<b>{_escape(a)}</b>" for a in added])
        self.notifier.send_message(f"✅ Added keyword(s): {added_str}\n\nTotal keywords: <b>{len(current)}</b>")

    def _cmd_del_keyword(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/del_keyword &lt;keyword&gt;</code>")
            return

        target = args.strip().lower()
        current = self._get_active_keywords()
        updated = [k for k in current if k.lower() != target]

        if len(updated) == len(current):
            self.notifier.send_message(f"ℹ️ Keyword <b>{_escape(args)}</b> not found in active list.")
            return

        self.db.set_setting("keywords", updated)
        self._notify_change()
        self.notifier.send_message(f"🗑 Removed keyword <b>{_escape(args)}</b>.\n\nRemaining keywords: <b>{len(updated)}</b>")

    def _cmd_set_keywords(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/set_keywords &lt;k1, k2, ...&gt;</code>")
            return

        new_keywords = [k.strip() for k in args.split(",") if k.strip()]
        self.db.set_setting("keywords", new_keywords)
        self._notify_change()

        kw_list = ", ".join([f"<b>{_escape(k)}</b>" for k in new_keywords])
        self.notifier.send_message(f"✅ Overwrote keywords ({len(new_keywords)}):\n{kw_list}")

    def _cmd_add_location(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/add_location &lt;city or comma-separated list&gt;</code>")
            return

        new_locs = [l.strip() for l in args.split(",") if l.strip()]
        current = self._get_active_locations()
        added = []
        for loc in new_locs:
            if not any(loc.lower() == c.lower() for c in current):
                current.append(loc)
                added.append(loc)

        if not added:
            self.notifier.send_message("ℹ️ Specified location(s) already exist.")
            return

        self.db.set_setting("locations", current)
        self._notify_change()

        added_str = ", ".join([f"<b>{_escape(a)}</b>" for a in added])
        self.notifier.send_message(f"✅ Added location(s): {added_str}\n\nTotal locations: <b>{len(current)}</b>")

    def _cmd_del_location(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/del_location &lt;city&gt;</code>")
            return

        target = args.strip().lower()
        current = self._get_active_locations()
        updated = [l for l in current if l.lower() != target]

        if len(updated) == len(current):
            self.notifier.send_message(f"ℹ️ Location <b>{_escape(args)}</b> not found in active list.")
            return

        self.db.set_setting("locations", updated)
        self._notify_change()
        self.notifier.send_message(f"🗑 Removed location <b>{_escape(args)}</b>.\n\nRemaining locations: <b>{len(updated)}</b>")

    def _cmd_set_locations(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/set_locations &lt;loc1, loc2, ...&gt;</code>")
            return

        new_locs = [l.strip() for l in args.split(",") if l.strip()]
        self.db.set_setting("locations", new_locs)
        self._notify_change()

        loc_list = ", ".join([f"<b>{_escape(l)}</b>" for l in new_locs])
        self.notifier.send_message(f"✅ Overwrote locations ({len(new_locs)}):\n{loc_list}")

    def _cmd_set_radius(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/set_radius &lt;km&gt;</code> (e.g. <code>/set_radius 75</code>)")
            return

        try:
            radius = int(args.strip())
            if radius <= 0 or radius > 500:
                raise ValueError("Radius must be between 1 and 500 km")
        except ValueError as err:
            self.notifier.send_message(f"❌ Invalid radius: {err}")
            return

        self.db.set_setting("radius_km", radius)
        self._notify_change()
        self.notifier.send_message(f"✅ Updated search radius to <b>{radius} km</b>.")

    def _cmd_add_company(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/add_company &lt;personio company slug&gt;</code>")
            return

        slugs = [s.strip().lower() for s in args.split(",") if s.strip()]
        current = self._get_active_companies()
        added = []
        for slug in slugs:
            if slug not in current:
                current.append(slug)
                added.append(slug)

        if not added:
            self.notifier.send_message("ℹ️ Specified company already in ATS tracking list.")
            return

        self.db.set_setting("personio_companies", current)
        self._notify_change()

        comp_str = ", ".join([f"<b>{_escape(c)}</b>" for c in added])
        self.notifier.send_message(f"✅ Added Personio ATS company: {comp_str}\n\nTotal companies: <b>{len(current)}</b>")

    def _cmd_del_company(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/del_company &lt;slug&gt;</code>")
            return

        target = args.strip().lower()
        current = self._get_active_companies()
        updated = [c for c in current if c.lower() != target]

        if len(updated) == len(current):
            self.notifier.send_message(f"ℹ️ Company <b>{_escape(args)}</b> not found in active list.")
            return

        self.db.set_setting("personio_companies", updated)
        self._notify_change()
        self.notifier.send_message(f"🗑 Removed company <b>{_escape(args)}</b>.")

    def _cmd_trigger_sweep(self) -> None:
        self.notifier.send_message("🚀 Initiating immediate sweep across all active providers...")
        if self.on_sweep_request:
            try:
                counts = self.on_sweep_request()
                total = sum(counts.values())
                self.notifier.send_message(
                    f"🏁 <b>Sweep Complete!</b>\n"
                    f"Total new jobs: <b>{total}</b>\n"
                    f"(Arbeitsagentur={counts.get('arbeitsagentur', 0)}, ATS={counts.get('ats', 0)}, Email={counts.get('email', 0)})"
                )
            except Exception as e:
                self.notifier.send_message(f"❌ Sweep failed: {_escape(str(e))}")
        else:
            self.notifier.send_message("ℹ️ On-demand sweep trigger is not linked in this mode.")

    def _cmd_reset_config(self) -> None:
        self.db.delete_setting("keywords")
        self.db.delete_setting("locations")
        self.db.delete_setting("radius_km")
        self.db.delete_setting("personio_companies")
        self._notify_change()
        self.notifier.send_message("🔄 All custom settings have been reset back to <code>config.yaml</code> defaults.")

    def _cmd_show_profile(self) -> None:
        try:
            from src.career_ops.profile_manager import ProfileManager
            pm = ProfileManager()
            self.notifier.send_message(pm.format_summary())
        except Exception as e:
            self.notifier.send_message(f"❌ Error loading profile: {_escape(str(e))}")

    def _cmd_set_name(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/set_name &lt;Full Name&gt;</code>")
            return
        from src.career_ops.profile_manager import ProfileManager
        pm = ProfileManager()
        pm.update_field("personal", "name", args.strip())
        self.notifier.send_message(f"✅ Name updated to: <b>{_escape(args.strip())}</b>")

    def _cmd_set_title(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/set_title &lt;Title / Degree&gt;</code>\nExample: <code>/set_title Chemiker / M.Sc. Analytik</code>")
            return
        from src.career_ops.profile_manager import ProfileManager
        pm = ProfileManager()
        pm.update_field("personal", "title", args.strip())
        self.notifier.send_message(f"✅ Title updated to: <b>{_escape(args.strip())}</b>")

    def _cmd_set_contact(self, args: str) -> None:
        parts = [p.strip() for p in args.split("|") if p.strip()]
        if not parts:
            self.notifier.send_message("⚠️ Usage: <code>/set_contact email@domain.com | +49 170 123456 | Berlin, Deutschland</code>")
            return
        from src.career_ops.profile_manager import ProfileManager
        pm = ProfileManager()
        if len(parts) >= 1 and "@" in parts[0]:
            pm.update_field("personal", "email", parts[0])
        if len(parts) >= 2:
            pm.update_field("personal", "phone", parts[1])
        if len(parts) >= 3:
            pm.update_field("personal", "location", parts[2])
            pm.update_field("personal", "address", parts[2])
        self.notifier.send_message("✅ Contact details updated! Type /profile to review.")

    def _cmd_add_skill(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/add_skill HPLC, GC-MS, Titration, GMP</code>")
            return
        skills = [s.strip() for s in args.split(",") if s.strip()]
        from src.career_ops.profile_manager import ProfileManager
        pm = ProfileManager()
        added = pm.add_skills(skills)
        if added:
            self.notifier.send_message(f"✅ Added {len(added)} skill(s): {_escape(', '.join(added))}")
        else:
            self.notifier.send_message("ℹ️ Specified skill(s) already exist in profile.")

    def _cmd_set_skills(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/set_skills HPLC, GC, UV-Vis, Titration</code>")
            return
        skills = [s.strip() for s in args.split(",") if s.strip()]
        from src.career_ops.profile_manager import ProfileManager
        pm = ProfileManager()
        pm.set_skills(skills)
        self.notifier.send_message(f"✅ Analytical skills set to ({len(skills)}): {_escape(', '.join(skills))}")

    def _cmd_set_salary(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/set_salary ca. 65.000 € brutto p.a.</code>")
            return
        from src.career_ops.profile_manager import ProfileManager
        pm = ProfileManager()
        pm.update_field("preferences", "salary_expectation", args.strip())
        self.notifier.send_message(f"✅ Salary expectation updated to: <b>{_escape(args.strip())}</b>")

    def _cmd_set_availability(self, args: str) -> None:
        if not args:
            self.notifier.send_message("⚠️ Usage: <code>/set_availability ab sofort / 1 Monat Kündigungsfrist</code>")
            return
        from src.career_ops.profile_manager import ProfileManager
        pm = ProfileManager()
        pm.update_field("preferences", "availability", args.strip())
        self.notifier.send_message(f"✅ Availability updated to: <b>{_escape(args.strip())}</b>")

    def _cmd_feed_cv(self, args: str) -> None:
        if not args or len(args) < 15:
            self.notifier.send_message("⚠️ Usage: <code>/feed_cv &lt;paste your CV text here&gt;</code>")
            return
        from src.career_ops.profile_manager import ProfileManager
        pm = ProfileManager()
        changes = pm.ingest_cv_text(args, source_filename="telegram_pasted_cv.txt")
        details = ", ".join(changes.keys()) if changes else "Text gespeichert"
        self.notifier.send_message(f"✅ <b>CV Text Ingested!</b>\nExtracted: {_escape(details)}\nType /profile to review.")

    def _cmd_feed_template(self, args: str) -> None:
        if not args or len(args) < 25:
            self.notifier.send_message("⚠️ Usage: <code>/feed_template &lt;paste custom German cover letter text with {company}, {title}, {matched_methods}&gt;</code>")
            return
        from src.career_ops.profile_manager import ProfileManager
        pm = ProfileManager()
        pm.save_template(args)
        self.notifier.send_message("✅ <b>Custom Cover Letter Template Saved!</b> Applications generated via /generate will follow this style.")
