from asynctest import test, Test, TestManager
from asyncirc.plugins import tracking
from blinker import signal
from _mocks import Client

client = Client()
client.netid = "mock for testing"
tracking.create_registry(client)

def join_example_user():
    signal("raw").send(client, text=":example!example@example.com JOIN #example exampleaccount :Example user")

def part_example_user():
    signal("raw").send(client, text=":example!example@example.com PART #example :Example reason")

def quit_example_user():
    signal("raw").send(client, text=":example!example@example.com QUIT :Example quit reason")

def kick_example_user():
    signal("raw").send(client, text=":someop!~someop@example.org KICK #example example :Example kick reason")

def user_not_in_example_channel():
    return "#example" not in client.tracking_registry.users["example"].channels

@test("should add users to the tracking database on channel joins")
def test_add_objects_to_database():
    join_example_user()

test_account_recording_on_extjoin = Test(None, "should track account names")
test_host_recording = Test(None, "should track hosts")
test_channel_membership_join_tracking = Test(None, "should track channel membership: joins")
test_channel_has_users_property = Test(None, "should allow retrieval of users from Channel.users")

@test_add_objects_to_database.done.connect
def check_objects_in_database(_):
    test_add_objects_to_database.succeed_if("example" in client.tracking_registry.users)
    test_account_recording_on_extjoin.succeed_if(client.tracking_registry.users["example"].account == "exampleaccount")
    test_host_recording.succeed_if(client.tracking_registry.users["example"].host == "example.com")
    test_channel_membership_join_tracking.succeed_if("#example" in client.tracking_registry.users["example"].channels)
    test_channel_has_users_property.succeed_if("example" in client.tracking_registry.channels["#example"].users)

@test("should track channel membership: parts")
def test_channel_membership_part_tracking():
    part_example_user()

@test_channel_membership_part_tracking.done.connect
def check_membership(_):
    test_channel_membership_part_tracking.succeed_if(user_not_in_example_channel())

@test("should remove users from the registry on quit")
def test_quit():
    quit_example_user()

@test_quit.done.connect
def check_quit_actually_removed_user(_):
    test_quit.succeed_if("example" not in client.tracking_registry.users)

test_user_return_after_quit = Test(None, "users are re-added to the registry on reconnect")

@test("should remove users from channels on kick")
def test_kick():
    join_example_user()
    test_user_return_after_quit.succeed_if("example" in client.tracking_registry.users and "#example" in client.tracking_registry.users["example"].channels)
    kick_example_user()

@test_kick.done.connect
def check_kick_removes_user_from_channel(_):
    test_kick.succeed_if(user_not_in_example_channel())

@test("should set topics for channels on 332 numerics")
def test_topic_332():
    signal("raw").send(client, text=":irc.example.com 332 botnick #example :the topic")

@test_topic_332.done.connect
def check_topic_332(_):
    test_topic_332.succeed_if(client.tracking_registry.channels["#example"].topic == "the topic")

@test("should set topics for channels when they are changed")
def test_topic_changed():
    signal("raw").send(client, text=":example!example@example.com TOPIC #example :the new topic")

@test_topic_changed.done.connect
def check_topic_changed(_):
    test_topic_changed.succeed_if(client.tracking_registry.channels["#example"].topic == "the new topic")

@test("should handle WHOX responses appropriately")
def test_whox():
    signal("raw").send(client, text=":irc.example.com 354 botnick #example ex2 example.net ex2 ex2")

@test_whox.done.connect
def check_whox(_):
    test_whox.succeed_if(
        "ex2" in client.tracking_registry.users and
        client.tracking_registry.users["ex2"].account == "ex2" and
        "ex2" in client.tracking_registry.channels["#example"].users
    )

@test("should handle standard WHO responses appropriately")
def test_standard_who():
    signal("raw").send(client, text=":irc.example.com 352 botnick #example ex3 example.net irc.example.com ex3 H :example 3")

@test_standard_who.done.connect
def check_standard_who(_):
    test_standard_who.succeed_if("ex3" in client.tracking_registry.channels["#example"].users)

@test("should handle channel MODE setting appropriately")
def test_initial_mode():
    signal("raw").send(client, text=":irc.example.com 324 botnick #example +cnt")

@test_initial_mode.done.connect
def check_initial_mode(_):
    test_initial_mode.succeed_if(client.tracking_registry.channels["#example"].mode == "+cnt")

@test("should handle end-WHO responses by setting channel state")
def test_end_who():
    signal("raw").send(client, text=":irc.example.com 315 botnick #example")

@test_end_who.done.connect
def check_end_who(_):
    test_end_who.succeed_if("who" in tracking.get_channel(client.netid, "#example").state)

@test("should track nickname changes")
def test_nickname_track():
    signal("raw").send(client, text=":ex2!ex2@example.net NICK ex4")

@test_nickname_track.done.connect
def check_nickname_track(_):
    test_nickname_track.succeed_if("ex2" in client.tracking_registry.users["ex4"].previous_nicks)

sync_done_send = Test(None, "should send sync-done when sync is done")
def sync_done_check(channel):
    sync_done_send.succeed_if(tracking.get_channel(client.netid, channel).state == {"who", "mode"})
signal("sync-done").connect(sync_done_check)

manager = TestManager([
    test_add_objects_to_database, test_account_recording_on_extjoin, test_host_recording,
    test_channel_membership_join_tracking, test_channel_membership_part_tracking, test_quit,
    test_kick, test_user_return_after_quit, test_topic_332, test_topic_changed,
    test_channel_has_users_property, test_whox, test_standard_who, test_initial_mode,
    test_end_who, test_nickname_track, sync_done_send
])

if __name__ == '__main__':
    manager.run_all()
