// Expected compile failure: the shared A::f has two final overriders.
struct A { virtual void f() {} };
struct B : virtual A { void f() override {} };
struct C : virtual A { void f() override {} };
struct D : B, C {};
int main() { D d; }
