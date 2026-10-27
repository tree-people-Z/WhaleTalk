"""One-off repair for comment rows written before bvid backfilling existed."""

from loguru import logger


async def backfill_comment_videos(bili, db, limit: int = 200) -> dict:
    updated = 0
    failed = []
    for row in db.get_comments_missing_video(limit=limit):
        aid = row.get('aid')
        bvid = row.get('bvid') or ''
        info = None
        try:
            if bvid:
                info = await bili.get_video_info(bvid)
            elif aid and hasattr(bili, 'get_video_info_by_aid'):
                info = await bili.get_video_info_by_aid(int(aid))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'回填视频信息失败 aid={aid}: {exc}')
        if not info or not info.get('bvid'):
            failed.append({'aid': aid, 'bvid': bvid})
            continue
        resolved = info['bvid']
        updated += db.update_comment_bvid(aid, resolved)
        try:
            db.ensure_video_record(
                resolved,
                int(info.get('aid') or aid or 0),
                str(info.get('title') or ''),
                str(info.get('owner') or ''),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'回填视频记录失败 {resolved}: {exc}')
    logger.info(f'历史视频回填完成: 更新 {updated} 条, 失败 {len(failed)} 组')
    return {'updated': updated, 'failed': failed}
