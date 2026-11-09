"""place_stats view：每個地點直接被幾筆片段指到，沒有片段的是 0。"""


def test_content_count_counts_content_pointing_at_each_place(conn):
    conn.executemany("INSERT INTO place (id, osm_type, osm_id, kind, name_ja, lat, lon, place_rank)"
                     " VALUES (?, 'way', ?, '景點', ?, 0, 0, 30)", [(1, 1, "浅草寺"), (2, 2, "雷門")])
    conn.executemany("INSERT INTO content (article_id, poi_id, poi_name, day_type, time, month)"
                     " VALUES (?, 1, '淺草寺', '平日', '早上', '1')", [("a",), ("b",)])

    assert conn.execute("SELECT id, content_count FROM place_stats ORDER BY id").fetchall() == [(1, 2), (2, 0)]
