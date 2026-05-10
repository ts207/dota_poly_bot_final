import requests
key = '5715C5A721591E946229DDA658FD1AFD'
partners = [0, 1, 2, 3]
for p in partners:
    r = requests.get(f'https://api.steampowered.com/IDOTA2Match_570/GetTopLiveGame/v1/?key={key}&partner={p}')
    data = r.json()
    games = data.get('game_list', [])
    print(f"Partner {p}: {len(games)} games")
    for g in games:
        r_team = g.get('team_name_radiant', 'Unknown')
        d_team = g.get('team_name_dire', 'Unknown')
        league_id = g.get('league_id')
        if r_team != 'Unknown' or d_team != 'Unknown':
            print(f"  {r_team} vs {d_team} | League: {league_id} | Lobby: {g.get('lobby_id')}")
