package com.bencaunt.kt2pose;

final class PoseMath {
    static final double[] CV_TO_AR = {1,0,0,0, 0,-1,0,0, 0,0,-1,0, 0,0,0,1};
    static double[] identity(int n) { double[] a = new double[n*n]; for (int i = 0; i < n; i++) a[i*n+i] = 1; return a; }
    static double[] multiply(double[] a, double[] b, int rows, int inner, int cols) {
        double[] c = new double[rows*cols];
        for (int r=0;r<rows;r++) for (int col=0;col<cols;col++) for (int k=0;k<inner;k++) c[r*cols+col] += a[r*inner+k]*b[k*cols+col];
        return c;
    }
    static double[] transpose(double[] a, int rows, int cols) {
        double[] b = new double[a.length];
        for (int r=0;r<rows;r++) for (int c=0;c<cols;c++) b[c*rows+r] = a[r*cols+c];
        return b;
    }
    static double[] fromColumnMajor(float[] a) {
        double[] result = new double[16];
        for (int r=0;r<4;r++) for (int c=0;c<4;c++) result[r*4+c] = a[c*4+r];
        return result;
    }
    static double[] worldFromTag(double[] camera, double[] cv) {
        return multiply(multiply(camera, CV_TO_AR, 4,4,4), cv, 4,4,4);
    }
    static double[] inverse3(double[] m) {
        double a=m[0],b=m[1],c=m[2],d=m[3],e=m[4],f=m[5],g=m[6],h=m[7],i=m[8];
        double det=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g);
        if (!Double.isFinite(det) || det <= 0) throw new IllegalArgumentException("Singular covariance");
        return new double[]{(e*i-f*h)/det,(c*h-b*i)/det,(b*f-c*e)/det,(f*g-d*i)/det,(a*i-c*g)/det,(c*d-a*f)/det,(d*h-e*g)/det,(b*g-a*h)/det,(a*e-b*d)/det};
    }
}
