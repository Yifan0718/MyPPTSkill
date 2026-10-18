// Expected compile failure: most-derived D must initialize A(int).
struct A { explicit A(int) {} };
struct B : virtual A { B() : A(1) {} };
struct C : virtual A { C() : A(2) {} };
struct D : B, C { D() {} };
int main() { D d; }
