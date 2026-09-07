#include "core/personal_proxy_policy.h"
#include <cassert>
#include <iostream>
int main() {
    using P = Core::PersonalProxyPolicy;
    using S = P::State;
    P p;
    assert(p.update(0,false,false,false)==S::Waiting);
    assert(p.update(60000,false,false,false)==S::Waiting);
    // Ready includes the logged-out login connection.
    assert(p.update(60001,true,false,false)==S::Trying);
    assert(p.update(90000,true,false,false)==S::Trying);
    assert(p.update(90001,true,false,false)==S::Direct);
    assert(p.fallback());
    assert(p.update(90002,true,true,true)==S::DirectConnected);
    assert(p.update(100000,true,false,false)==S::Direct);
    assert(p.update(200000,false,false,false)==S::Direct);
    assert(!p.everConnected());
    P restart;
    assert(restart.update(0,true,false,false)==S::Trying);
    assert(!restart.fallback());
    assert(restart.update(10000,true,true,false)==S::ProxyConnected);
    assert(restart.everConnected());
    assert(restart.update(50000,true,false,false)==S::Trying);
    assert(restart.update(79999,true,false,false)==S::Trying);
    assert(restart.update(80000,true,false,false)==S::Direct);
    P recovered;
    recovered.update(0,true,false,false);
    assert(recovered.update(29999,true,true,false)==S::ProxyConnected);
    assert(recovered.update(30000,true,false,false)==S::Trying);
    assert(recovered.update(59999,true,false,false)==S::Trying);
    assert(recovered.update(60000,true,false,false)==S::Direct);
    P invalid;
    assert(invalid.update(0,true,false,true)==S::Direct);
    assert(invalid.update(1,true,true,false)==S::DirectConnected);
    std::cout << "Policy cases passed: timeout boundaries, login readiness, recovery, latch, restart.\n";
}
