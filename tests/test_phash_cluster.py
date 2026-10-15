import random

from coverup.matching.cluster import cluster_candidates
from coverup.matching.phash import dhash, hamming, is_blank, trim_uniform_margins
from coverup.model import Candidate

W = H = 64


def gradient(w=W, h=H):
    return [int(255 * x / (w - 1)) for _y in range(h) for x in range(w)]


def checker(w=W, h=H, size=8):
    return [255 if ((x // size) + (y // size)) % 2 == 0 else 0 for y in range(h) for x in range(w)]


def noisy(pixels, amount=6, seed=1):
    rnd = random.Random(seed)
    return [max(0, min(255, p + rnd.randint(-amount, amount))) for p in pixels]


def test_identical_images_have_distance_zero():
    assert hamming(dhash(gradient(), W, H), dhash(gradient(), W, H)) == 0


def test_recompressed_image_is_close():
    a = dhash(gradient(), W, H)
    b = dhash(noisy(gradient()), W, H)
    assert hamming(a, b) <= 10


def test_different_artwork_is_far():
    assert hamming(dhash(gradient(), W, H), dhash(checker(), W, H)) > 10


def test_scaled_up_image_hashes_the_same():
    small = gradient(32, 32)
    big = [small[(y // 2) * 32 + (x // 2)] for y in range(64) for x in range(64)]
    assert hamming(dhash(small, 32, 32), dhash(big, 64, 64)) <= 4


def test_blank_detection():
    assert is_blank([128] * 100)
    assert not is_blank(gradient())


def test_trim_margins_recovers_the_same_hash():
    inner = checker(48, 48, 6)
    pad = 8
    w = 48 + 2 * pad
    padded = []
    for y in range(w):
        for x in range(w):
            inside = pad <= x < pad + 48 and pad <= y < pad + 48
            padded.append(inner[(y - pad) * 48 + (x - pad)] if inside else 255)
    trimmed, tw, th = trim_uniform_margins(padded, w, w)
    assert (tw, th) == (48, 48)
    assert hamming(dhash(trimmed, tw, th), dhash(inner, 48, 48)) <= 4


def test_clustering_groups_similar_and_splits_different():
    g, c = dhash(gradient(), W, H), dhash(checker(), W, H)
    cands = [
        Candidate("caa", "1", "u1", phash=g),
        Candidate("itunes", "2", "u2", phash=dhash(noisy(gradient()), W, H)),
        Candidate("deezer", "3", "u3", phash=c),
        Candidate("web", "4", "u4", phash=None),
    ]
    clusters = cluster_candidates(cands)
    sizes = sorted(len(cl.members) for cl in clusters)
    assert sizes == [1, 1, 2]
    two = next(cl for cl in clusters if len(cl.members) == 2)
    assert two.providers == {"caa", "itunes"}
