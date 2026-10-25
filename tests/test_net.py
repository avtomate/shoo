import ipaddress
import unittest

from shoo.net import ESTABLISHED, LISTEN, NetView, Sock, parse_addr

LO = ipaddress.ip_address("127.0.0.1")
ANY = ipaddress.ip_address("0.0.0.0")
OUTSIDE = ipaddress.ip_address("203.0.113.9")


def view(socks, inodes_by_pid):
    return NetView(socks, inodes_of=lambda pid: inodes_by_pid.get(pid, set()))


class Addresses(unittest.TestCase):
    def test_ipv4_and_ipv4_mapped_ipv6(self):
        self.assertEqual(parse_addr("0100007F:1F90"), (LO, 8080))
        self.assertEqual(parse_addr("0000000000000000FFFF00000100007F:1F90"), (LO, 8080))

    def test_ipv6_loopback(self):
        ip, port = parse_addr("00000000000000000000000001000000:0050")
        self.assertTrue(ip.is_loopback)
        self.assertEqual(port, 80)


class Connections(unittest.TestCase):
    listen = Sock((ANY, 5173), (ANY, 0), LISTEN, "1")

    def test_listening_ports(self):
        self.assertEqual(view([self.listen], {10: {"1"}}).listening_ports(10), (5173,))

    def test_remote_client_counts(self):
        socks = [self.listen, Sock((LO, 5173), (OUTSIDE, 50000), ESTABLISHED, "2")]
        self.assertEqual(view(socks, {10: {"1", "2"}}).outside_connections({10}), 1)

    def test_loopback_peer_inside_the_tree_does_not_count(self):
        socks = [Sock((LO, 5173), (LO, 40000), ESTABLISHED, "2"),
                 Sock((LO, 40000), (LO, 5173), ESTABLISHED, "3")]
        self.assertEqual(view(socks, {10: {"2"}, 11: {"3"}}).outside_connections({10, 11}), 0)

    def test_loopback_peer_outside_the_tree_counts(self):
        # e.g. an SSH tunnel: sshd holds the other end
        socks = [self.listen, Sock((LO, 5173), (LO, 40000), ESTABLISHED, "2"),
                 Sock((LO, 40000), (LO, 5173), ESTABLISHED, "3")]
        self.assertEqual(view(socks, {10: {"1", "2"}, 99: {"3"}}).outside_connections({10}), 1)

    def test_unknown_peer_is_assumed_to_be_a_user(self):
        socks = [self.listen, Sock((LO, 5173), (LO, 40000), ESTABLISHED, "2")]
        self.assertEqual(view(socks, {10: {"1", "2"}}).outside_connections({10}), 1)

    def test_outbound_connections_do_not_count(self):
        # An abandoned agent's keep-alive to an API, or a dev server's pool to a local database.
        socks = [self.listen,
                 Sock((LO, 51000), (OUTSIDE, 443), ESTABLISHED, "4"),
                 Sock((LO, 51001), (LO, 5432), ESTABLISHED, "5"),
                 Sock((LO, 5432), (LO, 51001), ESTABLISHED, "6")]
        self.assertEqual(view(socks, {10: {"1", "4", "5"}, 99: {"6"}}).outside_connections({10}), 0)

    def test_fd_directories_are_read_once(self):
        calls = []
        v = NetView([self.listen], inodes_of=lambda pid: calls.append(pid) or {"1"})
        v.listening_ports(10)
        v.outside_connections({10})
        self.assertEqual(calls, [10])


if __name__ == "__main__":
    unittest.main()
