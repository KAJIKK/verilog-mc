"""Summarize sampled Minecraft server stacks from `jfr print --json`."""
import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('json_profile',type=Path)
    args = parser.parse_args()
    events = json.loads(args.json_profile.read_text())['recording']['events']
    threads,leaves = Counter(),Counter()
    server = []
    for event in events:
        data = event['values']
        thread = data.get('sampledThread') or data.get('eventThread') or {}
        name = thread.get('javaName') or thread.get('osName') or '?'
        threads[name] += 1
        if name != 'Server thread':
            continue
        frames = (data.get('stackTrace') or {}).get('frames',[])
        stack = [f'{frame["method"]["type"]["name"].replace("/",".")}.{frame["method"]["name"]}' for frame in frames]
        if stack:
            leaves[stack[0]] += 1
            server.append(stack)
    print(json.dumps({'samples':len(events),'thread_samples':threads.most_common(10),
                      'server_samples':len(server),'server_leaf_samples':leaves.most_common(20),
                      'example_server_stacks':server[:5]},indent=2))


if __name__ == '__main__':
    main()
