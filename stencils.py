"""Static boilerplate templates for common algorithmic patterns — one-click
insertion so you can focus on the problem-specific logic."""

from __future__ import annotations

STENCILS: dict[str, str] = {
    "Binary Search": '''def binary_search(nums: list[int], target: int) -> int:
    lo, hi = 0, len(nums) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if nums[mid] == target:
            return mid
        elif nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
''',
    "Two Pointers": '''def two_pointers(nums: list[int]) -> None:
    left, right = 0, len(nums) - 1
    while left < right:
        # ... compare / process nums[left] and nums[right] ...
        left += 1
        right -= 1
''',
    "Sliding Window": '''def sliding_window(nums: list[int], k: int) -> None:
    window_sum = 0
    left = 0
    for right, value in enumerate(nums):
        window_sum += value
        if right - left + 1 > k:
            window_sum -= nums[left]
            left += 1
        # ... use window_sum for the window [left, right] ...
''',
    "BFS (graph/grid)": '''from collections import deque

def bfs(start, neighbors_of):
    visited = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbor in neighbors_of(node):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
''',
    "DFS (recursive)": '''def dfs(node, neighbors_of, visited=None):
    if visited is None:
        visited = set()
    visited.add(node)
    for neighbor in neighbors_of(node):
        if neighbor not in visited:
            dfs(neighbor, neighbors_of, visited)
    return visited
''',
    "Trie": '''class TrieNode:
    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.is_word = False


class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word: str) -> None:
        node = self.root
        for ch in word:
            node = node.children.setdefault(ch, TrieNode())
        node.is_word = True

    def search(self, word: str) -> bool:
        node = self.root
        for ch in word:
            if ch not in node.children:
                return False
            node = node.children[ch]
        return node.is_word
''',
    "Union-Find": '''class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> bool:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1
        return True
''',
    "1D DP": '''def solve_dp(n: int):
    dp = [0] * (n + 1)
    dp[0] = 0  # base case
    for i in range(1, n + 1):
        dp[i] = dp[i - 1]  # ... transition ...
    return dp[n]
''',
    "2D DP (grid)": '''def solve_dp_2d(m: int, n: int):
    dp = [[0] * n for _ in range(m)]
    for i in range(m):
        for j in range(n):
            if i == 0 and j == 0:
                continue  # base case
            # dp[i][j] = ... transition using dp[i-1][j] / dp[i][j-1] ...
    return dp[m - 1][n - 1]
''',
    "Monotonic Stack": '''def monotonic_stack(nums: list[int]) -> list[int]:
    result = [-1] * len(nums)
    stack: list[int] = []  # indices, values kept increasing (or decreasing)
    for i, value in enumerate(nums):
        while stack and nums[stack[-1]] < value:
            result[stack.pop()] = i
        stack.append(i)
    return result
''',
}
