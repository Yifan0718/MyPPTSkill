// Expected compile failure: D has two A subobjects.
struct A { int id = 0; };
struct B : A {};
struct C : A {};
struct D : B, C {};
int main() { D d; A& a = d; return a.id; }
