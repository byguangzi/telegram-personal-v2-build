#include "core/personal_archive_rules.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <iostream>

int main() {
    Core::PersonalArchiveRules first, second;
    assert(first.observe(101));
    assert(!first.observe(101));
    assert(first.contains(101) && !second.contains(101));
    Core::PersonalArchiveRules restarted;
    assert(restarted.parse(first.serialize()) && restarted.contains(101));
    restarted.set(101, false);
    assert(!restarted.contains(101) && !restarted.observe(101));
    assert(first.parse(restarted.serialize()) && !first.observe(101));
    first.set(101, true);
    assert(first.contains(101));
    const auto before = first.serialize();
    for (const auto bad : {"", "PERSONAL_ARCHIVE_2\n", "PERSONAL_ARCHIVE_1\nA0\n",
             "PERSONAL_ARCHIVE_1\nA12x\n", "PERSONAL_ARCHIVE_1\nA1\nR1\n",
             "PERSONAL_ARCHIVE_1\nA18446744073709551616\n", "PERSONAL_ARCHIVE_1\nA1"}) {
        assert(!first.parse(bad));
        assert(first.serialize() == before);
    }
    std::cout << "PASS: account isolation, persistence, release, rearchive, invalid-data rejection.\n";
}
